"""
Agente que gestiona las peticiones de los vendedores externos
"""
from flask import Flask, render_template, request
import socket
import argparse
import uuid 
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
    port = 9080
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
AgenteVendedorExterno = Agent('AgenteVendedorExterno', agn.AgenteVendedorExterno,
                          'http://%s:%d/comm' % (hostname, port),'http://%s:%d/Stop' % (hostname, port))


# direccion del agente directorio
DirectoryAgent = Agent('DirectoryAgent',
                       agn.Directory,
                       'http://%s:%d/Register' % (dhostname, dport),
                       'http://%s:%d/Stop' % (dhostname, dport))



#crear aplicacion servidor
app = Flask(__name__, template_folder="./templates")

def get_message_count():
    global mss_cnt
    if mss_cnt is None:
        mss_cnt = 0
    mss_cnt += 1
    return mss_cnt


#funcion que se comunica con el AgenteGestorDeProductos para añadir un producto a la BD
def anadir_producto(request):
    logger.info("Analizando petición de añadir producto")
    id_producto = uuid.uuid4()  #generate a random id
    vendedor = request.form["id_vendedor"]
    nombre =request.form["nombre_producto"]
    precio = int(int(request.form["precio_producto"])*100)
    peso = int(request.form["peso"])
    marca = request.form["marca"]
    categoria = request.form["categoria"]
    descripcion = request.form["descripcion_producto"]
    unidades = request.form["unidades"]
    tarjeta = request.form["tarjeta"]
    
    sujeto = ECSDIAmazon["Anadir_producto" + str(get_message_count())]
    grafo = Graph()
    grafo.add((sujeto, RDF.type, ECSDIAmazon.Anadir_producto))
    grafo.add((sujeto, ECSDIAmazon.Id_producto, Literal(id_producto, datatype=XSD.string)))
    grafo.add((sujeto, ECSDIAmazon.Vendedor, Literal(vendedor, datatype=XSD.string)))
    grafo.add((sujeto, ECSDIAmazon.Nombre_producto, Literal(nombre, datatype=XSD.string)))
    grafo.add((sujeto, ECSDIAmazon.Precio_producto, Literal(precio, datatype=XSD.int)))
    grafo.add((sujeto, ECSDIAmazon.Descripcion_producto, Literal(descripcion, datatype=XSD.string)))
    grafo.add((sujeto, ECSDIAmazon.Categoria, Literal(categoria, datatype=XSD.string)))
    grafo.add((sujeto, ECSDIAmazon.Marca, Literal(marca, datatype=XSD.string))) 
    grafo.add((sujeto, ECSDIAmazon.Peso_producto, Literal(peso, datatype=XSD.int)))
    grafo.add((sujeto, ECSDIAmazon.Tarjeta, Literal(tarjeta, datatype=XSD.string)))
    grafo.add((sujeto, ECSDIAmazon.Unidades, Literal(unidades, datatype=XSD.int)))
    

    # logger.info("Cogiendo informacion del AgenteGestorDeProductos")
    agente = get_agent_info(agn.AgenteGestorDeProductos, DirectoryAgent, AgenteVendedorExterno, get_message_count())
    logger.info("Enviando peticion de anadir producto al AgenteGestorDeProductos")
    respuesta_msg = send_message(build_message(
            grafo, perf=ACL.request, sender=AgenteVendedorExterno.uri, receiver=agente.uri, msgcnt=get_message_count(), 
            content=sujeto), agente.address)


    return render_template('prod_anadido.html')



@app.route("/", methods=["GET", "POST"])
def main():
    if request.method == "GET":
        return render_template("pg_vendedor_externo.html",)
    else:
        if request.form["submit"] == "Añadir":
            return anadir_producto(request)


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

    gr = register_agent(AgenteVendedorExterno, DirectoryAgent, agn.AgenteVendedorExterno, get_message_count())
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
    # Ponemos en marcha el servidor Flask
    app.run(debug=True, host=hostname, port=port)
    # Esperamos a que acaben los behaviors
    ab1.join()
    logger.info('The End')