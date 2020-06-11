"""
Agente centro logistico
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
from datetime import datetime,timedelta

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
    port = 9015
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
AgenteCL = Agent('AgenteCL', agn.AgenteCL,
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

def calcularfechadeenviofinal(prioridad):
    """Calcula el dia aproximado de envio apartir de la prioridad(1-10),ahora es un factor de 1 y sumando 1"""
    x = datetime.now() + timedelta(days= (prioridad*1)) 
    return x.strftime("%Y-%m-%d") 

def gestionarEncargo(contenido, grafo):
    # generar_lotes
    # Asignar_transportista
    # Informar_que ha recibido_correctamente
    # Crear respuesta
    ##ERROR: No se sabe qpero esa aqui 
    logger.info("Gestionando Encargo de envio")
    
    logger.info("Asignando realizando negociacion")
    
    logger.info("Asignando transportista")
    transportista_asignado = "AgenteTransportista1"
    prioridad =  grafo.value(subject=contenido ,predicate=ECSDIAmazon.Prioridad)
    fecha_final = calcularfechadeenviofinal(int(prioridad))
    precio_envio = 2.0
    graf_aux = Graph()
    graf_aux.bind('default', ECSDIAmazon)
    contenido_responder = ECSDIAmazon["Responder-" + str(get_message_count())] 
    graf_aux.add((contenido_responder, RDF.type, ECSDIAmazon.Respuesta))
    graf_aux.add((contenido_responder, ECSDIAmazon.Precio_envio, Literal(precio_envio, datatype=XSD.float)))
    graf_aux.add((contenido_responder, ECSDIAmazon.Fecha_final, Literal(fecha_final, datatype=XSD.string)))
    graf_aux.add((contenido_responder, ECSDIAmazon.Transportista_asignado, Literal(transportista_asignado, datatype=XSD.string)))
    graf_aux.add((contenido_responder, ECSDIAmazon.Mensaje,Literal("Enviado",datatype=XSD.string)))
    return graf_aux
    
@app.route("/comm")
def comunicacion():
    message = request.args['content'] #cogo el contenido enviado
    grafo = Graph()
    grafo.parse(data=message)
    message_properties = get_message_properties(grafo)
    resultado_comunicacion = None

    if message_properties is None:
        # Respondemos que no hemos entendido el mensaje
        resultado_comunicacion = build_message(Graph(), ACL['not-understood'],
                                              sender=AgenteCL.uri, msgcnt=get_message_count())
    else:
        # Obtenemos la performativa
        if message_properties['performative'] != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            resultado_comunicacion = build_message(Graph(), ACL['not-understood'],
                                                  sender=AgenteCL.uri, msgcnt=get_message_count())
        else:
            #Extraemos el contenido que ha de ser una accion de la ontologia 
            contenido = message_properties['content']

            accion = grafo.value(subject=contenido, predicate=RDF.type)
            logger.info("La accion es: " + accion)
            # Si la acción es de tipo iniciar_venta empezamos
            if accion == ECSDIAmazon.Encargo_envio:
                resultado_comunicacion = gestionarEncargo(contenido, grafo)
                
    serialize = resultado_comunicacion.serialize(format='xml')

    return serialize, 200


@app.route("/Stop")
def stop():
    """
    Entrypoint que para el agente

    :return:
    """
    tidyup()
    shutdown_server()
    return "Parando Servidor"



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

    gr = register_agent(AgenteCL, DirectoryAgent, agn.AgenteCL, get_message_count())
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