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
from AgentUtil.OntoNamespaces import ECSDIAmazon, ACL, DSO
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
    port = 9003
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
AgenteGestorDeVentas = Agent('AgenteGestorDeVentas', agn.AgenteGestorDeVentas,
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

def registrarVenta(grafo):
    """ Funcion que registra la venta realizada a la base de datos"""
    logger.info("Registrando la venta")
    ontologyFile = open('../rdf/ventas')

    grafoVentas = Graph()
    grafoVentas.bind('default', ECSDIAmazon)
    grafoVentas.parse(ontologyFile, format='turtle')
    grafoVentas += grafo

    # Guardem el graf
    grafoVentas.serialize(destination='../data/ComprasDB', format='turtle')
    logger.info("Registro de venta finalizado")

def enviarVenta(contenido,grafo):
    # Enviar mensaje con la compra a enviador
    logger.info("Haciendo peticion envio")
    grafo.remove((contenido, RDF.type, ECSDIAmazon.PeticionCompra))
    sujeto = ECSDIAmazon['PeticionEnvio' + str(get_message_count())]
    grafo.add((sujeto, RDF.type, ECSDIAmazon.PeticionEnvio))

    for a, b, c in grafo:
        if a == contenido:
            grafo.remove((a, b, c))
            grafo.add((sujeto, b, c))
    logger.info("Enviando peticion envio")
    enviador = getAgentInfo(agn.EnviadorAgent, DirectoryAgent, AgenteGestorDeVentas, get_message_count())
    resultadoComunicacion = send_message(build_message(grafo,
                                                       perf=ACL.request, sender=AgenteGestorDeVentas.uri,
                                                       receiver=enviador.uri,
                                                       msgcnt=get_message_count(), contenido=sujeto), enviador.address)
    logger.info("Enviada peticion envio")


def vender_productos(contenido, grafo):
    """Funcion que efectua el proceso de venta mediante threads"""
    
    logger.info("Peticion de venta recibida")
    # # Guardar Venta 
    # thread = Thread(target=registrarVenta, args=(grafo,))
    # thread.start()

    tarjeta = grafo.value(subject=contenido, predicate=ECSDIAmazon.Tarjeta)

    grafo_factura = Graph()
    grafo_factura.bind('default', ECSDIAmazon)

    logger.info("Generando factura")
    # Crear factura
    nueva_factura = ECSDIAmazon['Factura' + str(get_message_count())]
    grafo_factura.add((nueva_factura, RDF.type, ECSDIAmazon.Factura))
    grafo_factura.add((nueva_factura, ECSDIAmazon.Tarjeta, Literal(tarjeta, datatype=XSD.int)))

    venta = grafo.value(subject=contenido, predicate=ECSDIAmazon.De)

    precio_total = 0
    for producto in grafo.objects(subject=venta, predicate=ECSDIAmazon.Contiene):
        grafo_factura.add((producto, RDF.type, ECSDIAmazon.Producto))

        nombreProducto = grafo.value(subject=producto, predicate=ECSDIAmazon.Nombre_producto)
        grafo_factura.add((producto, ECSDIAmazon.Nombre_producto, Literal(nombreProducto, datatype=XSD.string)))

        precioProducto = grafo.value(subject=producto, predicate=ECSDIAmazon.Precio_producto)
        grafo_factura.add((producto, ECSDIAmazon.Precio_producto, Literal(float(precioProducto), datatype=XSD.float)))
        precio_total += float(precioProducto)

        grafo_factura.add((nueva_factura, ECSDIAmazon.FormadaPor, URIRef(producto)))


    grafo_factura.add((nueva_factura, ECSDIAmazon.Precio_total, Literal(precio_total, datatype=XSD.float)))
    #No es estrictamente necesario la siguiente parte por que ya ponemos el precio_total a la factura
    # ini_venta = grafo.value(predicate=RDF.type, object=ECSDIAmazon.Iniciar_venta)
    # grafo.add((ini_venta, ECSDIAmazon.Precio_Total, Literal(precio_total, datatype=XSD.float)))

    # Enviar encargo de envio al Centro logistico
    # thread = Thread(target=enviarVenta, args=(grafo, contenido))
    # thread.start()

    logger.info("Devolviendo factura")
    return grafo_factura


@app.route("/comm")
def communication():
    message = request.args['content'] #cogo el contenido enviado
    grafo = Graph()
    grafo.parse(data=message)
    logger.info('--Envian una comunicacion')
    message_properties = get_message_properties(grafo)

    resultado_comunicacion = None

    if message_properties is None:
        # Respondemos que no hemos entendido el mensaje
        resultado_comunicacion = build_message(Graph(), ACL['not-understood'],
                                              sender=AgenteGestorDeVentas.uri, msgcnt=get_message_count())
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
            # Si la acción es de tipo iniciar_venta empezamos
            if accion == ECSDIAmazon.Iniciar_venta:
                resultado_comunicacion = vender_productos(contenido, grafo)
                
    logger.info('Antes de serializar la respuesta')
    serialize = resultado_comunicacion.serialize(format='xml')

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
    gr = register_agent(AgenteGestorDeVentas, DirectoryAgent, agn.AgenteGestorDeVentas, get_message_count())
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
    print('The End')