# -*- coding: utf-8 -*-
"""
Agente que gestiona las peticiones de los usuarios
"""
from flask import Flask, render_template, request
import socket
import argparse
from rdflib import Namespace, Graph, RDF, URIRef, Literal, XSD
from AgentUtil.Agent import Agent
from AgentUtil.Logging import config_logger
from AgentUtil.OntoNamespaces import ECSDIAmazon, ACL
from AgentUtil.ACLMessages import get_agent_info, send_message, build_message, get_message_properties, register_agent
from multiprocessing import Process
from AgentUtil.FlaskServer import shutdown_server
from multiprocessing import Queue
from math import floor

__author__ = 'Amazon'


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
    port = 9090
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

queue = Queue()
# Contador de mensajes, por si queremos hacer un seguimiento
mss_cnt = 0

#crear agente
AgenteUsuario = Agent('AgenteUsuario', agn.AgenteUsuario,
                          'http://%s:%d/comm' % (hostname, port),'http://%s:%d/Stop' % (hostname, port))


# direccion del agente directorio
DirectoryAgent = Agent('DirectoryAgent',
                       agn.Directory,
                       'http://%s:%d/Register' % (dhostname, dport),
                       'http://%s:%d/Stop' % (dhostname, dport))



#crear aplicacion servidor
app = Flask(__name__, template_folder="./templates")

# global dsgraph triplestore
dsgraph = Graph()

lista_de_productos = []

def get_message_count():
    global mss_cnt
    if mss_cnt is None:
        mss_cnt = 0
    mss_cnt += 1
    return mss_cnt

#ruta definida para mostrar la pagina principal con diferente opciones
@app.route("/")
def main():
    print("Dentro del main / ")
    return render_template("pg_usuario.html")



#funcion que se encarga de pedir la busqueda de productos al agente GestorDeProductos
def peticion_buscar(request):
    global lista_de_productos
    logger.info("Preparando la peticion de busqueda")
    
    #accion: Buscar_productos
    contenido = ECSDIAmazon["Buscar_productos"+str(get_message_count())]
    grafo = Graph()
    grafo.add((contenido, RDF.type, ECSDIAmazon.Buscar_productos))
    
    nombre_producto = request.form["nombre"]
    #agregamos el nombre del producto
    if nombre_producto:
        print(nombre_producto)
        nombre_sujeto = ECSDIAmazon["Restriccion_nombre" + str(get_message_count)]
        grafo.add((nombre_sujeto, RDF.type, ECSDIAmazon.Restriccion_nombre))
        grafo.add((nombre_sujeto, ECSDIAmazon.Nombre, Literal(nombre_producto, datatype=XSD.string)))
        grafo.add((contenido, ECSDIAmazon.Restringe, URIRef(nombre_sujeto)))
    ##El precio se recibe en euros pero se ha de cambiar a centimos de euro
        # if(request.form['precio_min']):
    # print("el precio minimo es :")
    # if request.form['precio_min'] == "" or request.form['precio_min'] == "0":
    # else: print ("It's not empty")
    # print(int(request.form['precio_min']))
    precio_min = request.form['precio_min']
    print("El precio minimo es:")
    print(precio_min)
        # else:
        # precio_min = 1
        # if(request.form['precio_max']):
    precio_max = request.form['precio_max']
    print(precio_max)
    # agregamos el rango de precios 
    if precio_min != "" or precio_max != "":
        precio_sujeto = ECSDIAmazon['Restriccion_precio' + str(get_message_count())]
        grafo.add((precio_sujeto, RDF.type, ECSDIAmazon.Restriccion_precio))
        if precio_min != "":
            if precio_min == "0":
                precio_min = 0
            else:
                print(int(floor(float(request.form['precio_min'])*100)))
                precio_min = int((float(request.form['precio_min'])*100)//1)

            grafo.add((precio_sujeto, ECSDIAmazon.Precio_minimo, Literal(precio_min)))
            print("Se ha agregado sin problemas")
        if precio_max != "":
            if precio_max == "0":
                precio_max = 0
            else:
                precio_max = int((float(request.form['precio_max'])*100)//1)
            grafo.add((precio_sujeto, ECSDIAmazon.Precio_maximo, Literal(precio_max)))
        grafo.add((contenido, ECSDIAmazon.Restringe, URIRef(precio_sujeto)))

    #pedimos informacion del agente GestorDeProductos
    logger.info("Cogiendo informacion del AgenteGestorDeProductos")
    agente = get_agent_info(agn.AgenteGestorDeProductos, DirectoryAgent, AgenteUsuario, get_message_count())
    logger.info("Enviando peticion de busqueda al AgenteGestorDeProductos")
    respuesta_msg = send_message(build_message(
            grafo, perf=ACL.request, sender=AgenteUsuario.uri, receiver=agente.uri, msgcnt=get_message_count(), 
            content=contenido), agente.address)

    
    lista_de_productos = []
    for item in respuesta_msg.subjects(RDF.type, ECSDIAmazon.Producto):
        product = dict(
            id_producto=str(respuesta_msg.value(subject=item, predicate=ECSDIAmazon.Id_producto)),
            nombre_producto=str(respuesta_msg.value(subject=item, predicate=ECSDIAmazon.Nombre_producto)),
            precio_producto=int(respuesta_msg.value(subject=item, predicate=ECSDIAmazon.Precio_producto))/100,
            descripcion_producto=str(respuesta_msg.value(subject=item, predicate=ECSDIAmazon.Descripcion_producto)),
            categoria=str(respuesta_msg.value(subject=item, predicate=ECSDIAmazon.Categoria)),
            marca=str(respuesta_msg.value(subject=item, predicate=ECSDIAmazon.Marca)),
            peso=str(respuesta_msg.value(subject=item, predicate=ECSDIAmazon.Peso_producto))
        )
        lista_de_productos.append(product)

    logger.info("Resultado de busqueda")
    print(lista_de_productos)
    #mostramos los productos
    return render_template('buscar.html', productos=sorted(lista_de_productos, key=lambda p_list: p_list["precio_producto"]), b=True)



def iniciar_venta(request):
    global lista_de_productos
    logger.info("Analizando la peticion de compra")
    mi_compra = []
    #coge los indices marcados
    for p in request.form.getlist("checkbox"):
        mi_compra.append(lista_de_productos[int(p)])
    

    #cogo info de la compra
    tarjeta = int(request.form['tarjeta'])
    direccion = str(request.form['direccion'])
    ciudad = str(request.form['ciudad'])
    codigo_postal = int(request.form['codigo_postal'])
    prioridad = int(request.form['prioridad']) #va entre 1 y 10, de menor a mayor

    #preparo el grafo para comunicarme con el AgenteGestorDeVenta
    #accion: Iniciar_venta
    contenido = ECSDIAmazon["Iniciar_venta" + str(get_message_count())]
    grafo_venta = Graph()
    grafo_venta.add((contenido, RDF.type, ECSDIAmazon.Iniciar_venta))
    grafo_venta.add((contenido, ECSDIAmazon.Tarjeta, Literal(tarjeta, datatype=XSD.int)))
    grafo_venta.add((contenido, ECSDIAmazon.Prioridad, Literal(prioridad, datatype=XSD.int)))
    
    direccion_cliente = ECSDIAmazon["Direccion"+ str(get_message_count())]
    grafo_venta.add((direccion_cliente, RDF.type, ECSDIAmazon.Direccion))
    grafo_venta.add((direccion_cliente, ECSDIAmazon.Direccion, Literal(direccion, datatype=XSD.string)))
    grafo_venta.add((direccion_cliente, ECSDIAmazon.Ciudad, Literal(ciudad, datatype=XSD.string)))
    grafo_venta.add((direccion_cliente, ECSDIAmazon.Codigo_postal, Literal(codigo_postal, datatype=XSD.int)))

    venta = ECSDIAmazon["Venta"+str(get_message_count())]
    grafo_venta.add((venta, RDF.type, ECSDIAmazon.Venta))
    grafo_venta.add((venta, ECSDIAmazon.Destino, URIRef(direccion_cliente)))


    logger.info("Mi lista de productos")
    print(lista_de_productos)
    logger.info("Mi compra")
    print(mi_compra)

    for producto in mi_compra:
        s = producto["id_producto"]
        print(s)
        #sujeto = ECSDIAmazon + s
        url = ECSDIAmazon
        sujeto = url.term(producto["id_producto"])
        print(sujeto)
        print()
        #esta parte habria que revisar
        grafo_venta.add((sujeto, RDF.type, ECSDIAmazon.Producto))
        grafo_venta.add((sujeto, ECSDIAmazon.Id_producto, Literal(producto['id_producto'], datatype=XSD.string)))
        grafo_venta.add((sujeto, ECSDIAmazon.Nombre_producto, Literal(producto['nombre_producto'], datatype=XSD.string)))
        grafo_venta.add((sujeto, ECSDIAmazon.Precio_producto, Literal(producto['precio_producto'], datatype=XSD.float)))
        grafo_venta.add((sujeto, ECSDIAmazon.Descripcion_producto, Literal(producto['descripcion_producto'], datatype=XSD.string)))
        grafo_venta.add((sujeto, ECSDIAmazon.Categoria, Literal(producto['categoria'], datatype=XSD.string)))
        grafo_venta.add((sujeto, ECSDIAmazon.Marca, Literal(producto['marca'], datatype=XSD.string)))
        grafo_venta.add((sujeto, ECSDIAmazon.Peso_producto, Literal(producto['peso'], datatype=XSD.int)))
        grafo_venta.add((venta, ECSDIAmazon.Contiene, URIRef(sujeto)))
    
    grafo_venta.add((contenido, ECSDIAmazon.De, URIRef(venta)))

    logger.info("Cogiendo informacion del AgenteGestorDeVentas")
    print("--------------contenido---------------")
    print(contenido)
    
    agente = get_agent_info(agn.AgenteGestorDeVentas, DirectoryAgent, AgenteUsuario, get_message_count())
    logger.info("Enviando peticion de iniciar venta al AgenteGestorDeVentas")
    print(agente.name)
    print(agente.address)
    print(agente.uri)
    respuesta_msg = send_message(build_message(
            grafo_venta, perf=ACL.request, sender=AgenteUsuario.uri, receiver=agente.uri, msgcnt=get_message_count(), 
            content=contenido), agente.address)
    
    logger.info("Respuesta recibida")
    
    #obtenemos valores factura, productos y tarjeta asocida a dicha factura de la compra para mostrar al usuario
    venta_factura = respuesta_msg.value(predicate=RDF.type, object=ECSDIAmazon.Factura)
    venta_tarjeta = respuesta_msg.value(subject=venta_factura, predicate=ECSDIAmazon.Tarjeta)
    venta_precio_total = respuesta_msg.value(subject=venta_factura, predicate=ECSDIAmazon.Precio_total)
    
    venta_productos = respuesta_msg.subjects(object=ECSDIAmazon.Producto)
    productos_factura = []
    for prod in venta_productos:
        product = dict(
            nombre_producto=str(respuesta_msg.value(subject=prod, predicate=ECSDIAmazon.Nombre_producto)),
            precio_producto=float(respuesta_msg.value(subject=prod, predicate=ECSDIAmazon.Precio_producto)),
        )
        # p = [respuesta_msg.value(subject=prod, predicate=ECSDIAmazon.Nombre_producto), respuesta_msg.value(subject=prod, predicate=ECSDIAmazon.Precio_producto)]
        print(product)
        productos_factura.append(product)

    #render de factura
    return render_template('informar_venta.html', productos=productos_factura, tarjeta=venta_tarjeta, precio_total=venta_precio_total)


#busqueda: get para mostrar los filtros de productos y post para atender la peticion de filtros
@app.route("/buscar", methods=["GET","POST"])
def buscar_productos():
    print("Dentro del /buscar")
    if request.method == "GET":
        return render_template("buscar.html", productos=None)
    elif request.method == "POST":
        if request.form["submit"] == "Buscar":
            return peticion_buscar(request)
        elif request.form["submit"] == "Comprar":
            return iniciar_venta(request)

        

@app.route("/devolucion", methods=["GET", "POST"])
def devolver_productos():
    return True



@app.route("/Stop")
def stop():
    """
    Entrypoint que para el agente

    :return:
    """
    tidyup()
    shutdown_server()
    return "Parando Servidor"


@app.route("/comm")
def comunicacion():
    """
    Entrypoint de comunicacion del agente
    """
    return "Nada"


def tidyup():
    """
    Acciones previas a parar el agente

    """
    global queue
    queue.put(0)
    pass

def register_message():
    """
    Envia un mensaje de registro al servicio de registro
    usando una performativa Request y una accion Register del
    servicio de directorio

    :param gmess:
    :return:
    """

    logger.info('Nos registramos')

    gr = register_agent(AgenteUsuario, DirectoryAgent, agn.AgenteUsuario, get_message_count())
    return gr


def agentbehavior1():
    """
    Un comportamiento del agente

    :return:
    """
    graf = register_message()
        

if __name__ == '__main__':
    # Ponemos en marcha los behaviors
    ab1 = Process(target=agentbehavior1)
    ab1.start()
    # Run server
    app.run(host=hostname, port=port, debug=True)
    # Esperamos a que acaben los behaviors
    ab1.join()
    logger.info('Final')