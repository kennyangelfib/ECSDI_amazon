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

# productos enconctrados
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

    precio_min = request.form['precio_min']
    precio_max = request.form['precio_max']
    # agregamos el rango de precios 
    if precio_min or precio_min:
        print(precio_min)
        print(precio_max)
        precio_sujeto = ECSDIAmazon['Restriccion_precio' + str(get_message_count())]
        grafo.add((precio_sujeto, RDF.type, ECSDIAmazon.Restriccion_precio))
        if precio_min:
            grafo.add((precio_sujeto, ECSDIAmazon.Precio_minimo, Literal(precio_min)))
        if precio_max:
            grafo.add((precio_sujeto, ECSDIAmazon.Precio_maximo, Literal(precio_max)))
        grafo.add((contenido, ECSDIAmazon.Restringe, URIRef(precio_sujeto)))

    #pedimos informacion del agente GestorDeProductos
    print("----------------------------1")
    agente = get_agent_info(agn.AgenteGestorDeProductos, DirectoryAgent, AgenteUsuario, get_message_count())
    print("----------------------------2")
    logger.info("Enviando peticion de busqueda al agente GestorDeProductos")
    grafo_busqueda = send_message(build_message(
            grafo, perf=ACL.request, sender=AgenteUsuario.uri, receiver=agente.uri, msgcnt=get_message_count(), 
            content=contenido), agente.address)
    
    logger.info("Resultado de busqueda recibido")
    lista_de_productos = []
    i_sujueto = {}
    i = 0

    sujetos = grafo_busqueda.objects(predicate=ECSDIAmazon.Muestra)
    for s in sujetos:
        i_sujueto[s] = i
        i+=1
        lista_de_productos.append({})

    for s, p, o in grafo_busqueda:
        if s in i_sujueto:
            producto = lista_de_productos[i_sujueto[s]]
            if p == ECSDIAmazon.Nombre:
                producto["Nombre"] = o
            elif p == ECSDIAmazon.Precio:
                producto["Precio"] = o
            elif p == ECSDIAmazon.Descripcion:
                producto["Descripcion"] = o
            elif p == ECSDIAmazon.Id:
                producto["Id"] = o
            elif p == ECSDIAmazon.Peso:
                producto["Peso"] = o
            elif p == RDF.type:
                producto["Sujeto"] = s
            lista_de_productos[i_sujueto[s]] = producto
    #mostramos los productos
    return render_template('buscar.html', productos=lista_de_productos)



#busqueda: get para mostrar los filtros de productos y post para atender la peticion de filtros
@app.route("/buscar", methods=["GET","POST"])
def buscar_productos():
    print("Dentro del /buscar")
    if request.method == "GET":
        return render_template("buscar.html", productos=None)
    elif request.method == "POST":
        if request.form["submit"] == "Buscar":
            return peticion_buscar(request)



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

    gr = register_agent(AgenteUsuario, DirectoryAgent, AgenteUsuario.uri, get_message_count())
    return gr


def agentbehavior1():
    """
    Un comportamiento del agente

    :return:
    """
    gr = register_message()
        

if __name__ == '__main__':
        # Ponemos en marcha los behaviors
    ab1 = Process(target=agentbehavior1)
    ab1.start()
    # Ponemos en marcha el servidor Flask
    app.run(debug=True, host=hostname, port=port, use_reloader=False)
    # Esperamos a que acaben los behaviors
    ab1.join()
    logger.info('Final')