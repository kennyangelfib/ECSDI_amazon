import argparse
import socket
import sys
from multiprocessing import Queue, Process
from threading import Thread

from flask import Flask, request
from rdflib import Namespace, Graph, RDF, URIRef, Literal, XSD
from AgentUtil.ACLMessages import get_agent_info, send_message, build_message, get_message_properties, register_agent
from AgentUtil.Agent import Agent
from AgentUtil.FlaskServer import shutdown_server
from AgentUtil.Logging import config_logger
from AgentUtil.OntoNamespaces import ECSDIAmazon, ACL,DSO
from rdflib.namespace import RDF, FOAF
from string import Template

#definimos los parametros de entrada (linea de comandos)
parser = argparse.ArgumentParser()
parser.add_argument('--open', help="Define si el servidor esta abierto al exterior o no", action='store_true', default=False)
parser.add_argument('--port', type=int, help="Puerto de comunicacion del agente")
parser.add_argument('--dhost', default=socket.gethostname(), help="Host del agente de directorio")
parser.add_argument('--dport', type=int, help="Puerto de comunicacion del agente de directorio")

# configuramos logger para imprimir
logger = config_logger(level=1) #1 para registrar todo (error i info)

# parsear los parametros de entrada
args = parser.parse_args()
if args.port is None:
    port = 9002
else:
    port = args.port

if args.open is None:
    hostname = '0.0.0.0'
else:
    hostname = '127.0.0.1'

if args.dport is None:
    dport = 9000
else:
    dport = args.dport

if args.dhost is None:
    dhostname = '127.0.0.1'
else:
    dhostname = args.dhost


#definimos un espacio de nombre
agn = Namespace("http://www.agentes.org#")

# Contador de mensajes, por si queremos hacer un seguimiento
mss_cnt = 0

#crear agente
AgenteGestorDeProductos = Agent('AgenteGestorDeProductos', agn.AgenteGestorDeProductos,
                          'http://%s:%d/comm' % (hostname, port),'http://%s:%d/Stop' % (hostname, port))


# direccion del agente directorio
DirectoryAgent = Agent('DirectoryAgent',
                       agn.Directory,
                       'http://%s:%d/Register' % (dhostname, dport),
                       'http://%s:%d/Stop' % (dhostname, dport))


# Global triplestore graph
dsGraph = Graph()
# Queue
queue = Queue()
#crear aplicacion servidor
app = Flask(__name__)

def get_message_count():
    global mss_cnt
    if mss_cnt is None:
        mss_cnt = 0
    mss_cnt += 1
    return mss_cnt


 #construimos el grafo de busqueda accediendo a la bd local
def aplicar_filtro(brand='(.*)', search_text='(.*)', precio_min=0, precio_max=sys.maxsize):
    productos = Graph()
    productos.parse('./rdf/productos.rdf')
    
    sparql_query = Template('''
        SELECT DISTINCT ?product ?id ?name ?description ?weight_grams ?category ?price_eurocents ?brand
        WHERE {
            ?product rdf:type ?type_prod .
            ?product ns:product_id ?id .
            ?product ns:product_name ?name .
            ?product ns:product_description ?description .
            ?product ns:weight_grams ?weight_grams .
            ?product ns:category ?category .
            ?product ns:price_eurocents ?price_eurocents .
            ?product ns:brand ?brand .
            FILTER (
                ?price_eurocents > $precio_min && 
                ?price_eurocents < $precio_max &&
                (regex(str(?name), '$search_text', 'i') || regex(str(?description), '$search_text', 'i') ) &&
                regex(str(?brand), '$brand', 'i')
            )
        }
    ''').substitute(dict(
        precio_min=precio_min,
        precio_max=precio_max,
        brand=brand,
        search_text=search_text
    )
    )

    #aplicamos la query
    resultado = productos.query(
        sparql_query,
        initNs=dict(
            foaf=FOAF,
            rdf=RDF,
            ns=ECSDIAmazon,
        )
    )

    grapfo_resultante = Graph()
    for p in resultado:
        subject = p.product
        grapfo_resultante.add((subject, RDF.type, ECSDIAmazon.Producto))
        grapfo_resultante.add((subject, ECSDIAmazon.Id_producto, p.id))
        grapfo_resultante.add((subject, ECSDIAmazon.Nombre_producto, p.name))
        grapfo_resultante.add((subject, ECSDIAmazon.Precio_producto, p.price_eurocents))
        grapfo_resultante.add((subject, ECSDIAmazon.Descripcion_producto, p.description))
        grapfo_resultante.add((subject, ECSDIAmazon.Categoria, p.category))
        grapfo_resultante.add((subject, ECSDIAmazon.Marca, p.brand))
        grapfo_resultante.add((subject, ECSDIAmazon.Peso_producto, p.weight_grams))

    return grapfo_resultante



#cogemos lo que nos envia el AgenteUsuario y hacemos la busqueda a la bd local de productos
def buscar_productos(contenido, grafo):
    logger.info("Analizando la peticion de busqueda")
    #en el contenido puedo tener dos restricciones: de nombre y precio (porque el predicato se relaciona con estas dos)
    restricciones = grafo.objects(contenido, ECSDIAmazon.Restringe)
    r_dict = {}
    for r in restricciones:
        if grafo.value(subject=r, predicate=RDF.type) == ECSDIAmazon.Restriccion_nombre:
            nombre = grafo.value(subject=r, predicate=ECSDIAmazon.Nombre)
            r_dict['search_text'] = nombre
            logger.info("Restriccion nombre: " + nombre)
        elif grafo.value(subject=r, predicate=RDF.type) == ECSDIAmazon.Restriccion_precio:
            
            precio_min = grafo.value(subject=r, predicate=ECSDIAmazon.Precio_minimo)
            precio_max = grafo.value(subject=r, predicate=ECSDIAmazon.Precio_maximo)
            if precio_min is not None:
                r_dict['precio_min'] = precio_min
            if precio_max is not None:
                r_dict['precio_max'] = precio_max

    return aplicar_filtro(**r_dict).serialize(format='xml')




#anade un producto a la BD local
def anadir_producto(grafo):
    logger.info("Añadiendo producto externo")
    id_producto = precio_producto = peso_producto = tarjeta = unidades = 0
    vendedor = nombre_producto = descripcion_producto = categoria = marca = ""

    for s,p,o in grafo:
        if str(p) == ECSDIAmazon + "Categoria":
            categoria = str(o)
        elif str(p) == ECSDIAmazon + "Peso_producto":
            peso_producto = str(o)
        elif str(p) == ECSDIAmazon + "Nombre_producto":
            nombre_producto = str(o)
        elif str(p) == ECSDIAmazon + "Marca":
            marca = str(o)
        elif str(p) == ECSDIAmazon + "Vendedor":
            vendedor = str(o)
        elif str(p) == ECSDIAmazon + "Id_producto":
            id_producto = str(o)
        elif str(p) == ECSDIAmazon + "Precio_producto":
            precio_producto = str(o)
        elif str(p) == ECSDIAmazon + "Descripcion_producto":
            descripcion_producto = str(o)
        elif str(p) == ECSDIAmazon + "Tarjeta":
            tarjeta = str(o)
        elif str(p) == ECSDIAmazon + "Unidades":
            unidades = str(o)
        
    
    # logger.info("Imprimiendo paramteros de entrada")
    # print(id_producto, " " , nombre_producto, " ", marca, " ", precio_producto, " ", 
    # descripcion_producto, " ", vendedor, " ", categoria, " ", peso_producto)

    producto = Graph()
    producto.parse("./rdf/productos.rdf")

    new_prod = ECSDIAmazon.__getattr__(str(id_producto))

    producto.add((new_prod, RDF.type, Literal(ECSDIAmazon + "product")))
    producto.add((new_prod, ECSDIAmazon.product_id, Literal(id_producto)))
    producto.add((new_prod, ECSDIAmazon.price_eurocents, Literal(precio_producto,datatype="http://www.w3.org/2001/XMLSchema#integer")))
    producto.add((new_prod, ECSDIAmazon.category, Literal(categoria)))
    producto.add((new_prod, ECSDIAmazon.seller, Literal(vendedor)))
    producto.add((new_prod, ECSDIAmazon.product_name, Literal(nombre_producto)))
    producto.add((new_prod, ECSDIAmazon.product_description, Literal(descripcion_producto)))
    producto.add((new_prod, ECSDIAmazon.brand, Literal(marca)))
    producto.add((new_prod, ECSDIAmazon.weight_grams, Literal(peso_producto,datatype="http://www.w3.org/2001/XMLSchema#integer")))
    producto.add((new_prod, ECSDIAmazon.credit_card, Literal(tarjeta)))
    producto.add((new_prod, ECSDIAmazon.unit, Literal(unidades)))
    
    logger.info("Escribiendo en la BD")
    producto.serialize("./rdf/productos.rdf")
    return grafo.serialize(format="xml")


@app.route("/comm")
def communication():
    message = request.args['content'] #cogo el contenido enviado
    grafo = Graph()
    logger.info('--Envian una comunicacion')
    grafo.parse(data=message)
    logger.info('--Envian una comunicacion')
    message_properties = get_message_properties(grafo)

    resultado_comunicacion = None

    if message_properties is None:
        # Respondemos que no hemos entendido el mensaje
        resultado_comunicacion = build_message(Graph(), ACL['not-understood'],
                                              sender=AgenteGestorDeProductos.uri, msgcnt=get_message_count())
    else:
        # Obtenemos la performativa
        if message_properties['performative'] != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            resultado_comunicacion = build_message(Graph(), ACL['not-understood'],
                                                  sender=DirectoryAgent.uri, msgcnt=get_message_count())
        else:
            # Extraemos el contenido que ha de ser una accion de la ontologia definida en Protege
            contenido = message_properties['content']
            accion = grafo.value(subject=contenido, predicate=RDF.type)
            logger.info("La accion es: " + accion)
            # Si la acción es de tipo busqueda  empezamos
            if accion == ECSDIAmazon.Buscar_productos:
                resultado_comunicacion = buscar_productos(contenido, grafo)
            elif accion == ECSDIAmazon.Anadir_producto:
                resultado_comunicacion = anadir_producto(grafo)
                
    logger.info('Antes de serializar la respuesta')
    serialize = resultado_comunicacion

    return serialize, 200



@app.route("/Stop")
def stop():
    """
    Entrypoint to the agent
    :return: string
    """

    tidyUp()
    shutdown_server()
    return "Stopping server"



#función llamada antes de cerrar el servidor
def tidyUp():
    """
    Previous actions for the agent.
    """

    global queue
    queue.put(0)

    pass


#función para registro de agente en el servicio de directorios
def register_message():
    """
    Envia un mensaje de registro al servicio de registro
    usando una performativa Request y una accion Register del
    servicio de directorio

    :param gmess:
    :return:
    """

    logger.info('Nos registramos')
    gr = register_agent(AgenteGestorDeProductos, DirectoryAgent, agn.AgenteGestorDeProductos, get_message_count())
    return gr



#funcion llamada al principio de un agente
def filterBehavior(queue):
    """
    Agent Behaviour in a concurrent thread.
    :param queue: the queue
    :return: something
    """
    graf = register_message()
    pass

if __name__ == '__main__':
    # Run behaviors
    ab1 = Process(target=filterBehavior, args=(queue,))
    ab1.start()

    # Run server
    app.run(host=hostname, port=port, debug=True)

    # Wait behaviors
    ab1.join()
    logger.info('The End')