# -*- coding: utf-8 -*-
"""
filename: SimpleDirectoryAgent
Antes de ejecutar hay que añadir la raiz del proyecto a la variable PYTHONPATH
Agente que lleva un registro de otros agentes
Utiliza un registro simple que guarda en un grafo RDF
El registro no es persistente y se mantiene mientras el agente funciona
Las acciones que se pueden usar estan definidas en la ontología
directory-service-ontology.owl
@author: javier
"""

from multiprocessing import Process, Queue
import socket
import argparse

from flask import Flask, request, render_template
from rdflib import Graph, RDF, Namespace, RDFS, BNode, URIRef
from rdflib.namespace import FOAF

from AgentUtil.OntoNamespaces import ACL, DSO, ECSDIAmazon
from AgentUtil.FlaskServer import shutdown_server
from AgentUtil.Agent import Agent
from AgentUtil.ACLMessages import build_message, get_message_properties
from AgentUtil.Logging import config_logger

__author__ = 'javier'

# Definimos los parametros de la linea de comandos
parser = argparse.ArgumentParser()
parser.add_argument('--open', help="Define si el servidor est abierto al exterior o no", action='store_true',
                    default=False)
parser.add_argument('--port', type=int, help="Puerto de comunicacion del agente")

# Logging
logger = config_logger(level=1)

# parsing de los parametros de la linea de comandos
args = parser.parse_args()

# Configuration stuff
if args.port is None:
    port = 9000
else:
    port = args.port

if args.open:
    hostname = '0.0.0.0'
else:
    hostname = '127.0.0.1'
    # socket.gethostname()

# Directory Service Graph
dsgraph = Graph()

# Vinculamos todos los espacios de nombre a utilizar
dsgraph.bind('acl', ACL)
dsgraph.bind('rdf', RDF)
dsgraph.bind('rdfs', RDFS)
dsgraph.bind('foaf', FOAF)
dsgraph.bind('dso', DSO)

agn = Namespace("http://www.agentes.org#")
DirectoryAgent = Agent('DirectoryAgent',
                       agn.Directory,
                       'http://%s:%d/Register' % (hostname, port),
                       'http://%s:%d/Stop' % (hostname, port))
app = Flask(__name__)
mss_cnt = 0

cola1 = Queue()  # Cola de comunicacion entre procesos


@app.route("/Register")
def register():
    """
    Entry point del agente que recibe los mensajes de registro
    La respuesta es enviada al retornar la funcion,
    no hay necesidad de enviar el mensaje explicitamente
    Asumimos una version simplificada del protocolo FIPA-request
    en la que no enviamos el mesaje Agree cuando vamos a responder
    :return:
    """

    def process_register():
        # Si la hay extraemos el nombre del agente (FOAF.name), el URI del agente
        # su direccion y su tipo

        logger.info('Peticion de registro')
        agn_add = gm.value(subject=content, predicate=DSO.Address)
        agn_name = gm.value(subject=content, predicate=FOAF.name)
        agn_uri = gm.value(subject=content, predicate=DSO.Uri)
        agn_type = gm.value(subject=content, predicate=DSO.AgentType)
        # agn_cp = gm.value(subject=content,predicate=ECSDIAmazon.Codigo_postal)

        
        # Añadimos la informacion en el grafo de registro vinculandola a la URI
        # del agente y registrandola como tipo FOAF.Agent
        dsgraph.add((agn_uri, RDF.type, FOAF.Agent))
        dsgraph.add((agn_uri, FOAF.name, agn_name))
        dsgraph.add((agn_uri, DSO.Address, agn_add))
        dsgraph.add((agn_uri, DSO.AgentType, agn_type))
        # if agn_cp is not None:       
        #     dsgraph.add((agn_uri, ECSDIAmazon.Codigo_postal, agn_cp))


        # Generamos un mensaje de respuesta
        return build_message(Graph(),
            ACL.confirm,
            sender=DirectoryAgent.uri,
            receiver=agn_uri,
            msgcnt=mss_cnt)

    def process_search():
        # Asumimos que hay una accion de busqueda que puede tener
        # diferentes parametros en funcion de si se busca un tipo de agente
        # o un agente concreto por URI o nombre
        # Podriamos resolver esto tambien con un query-ref y enviar un objeto de
        # registro con variables y constantes
        
        # IMPORTANTE!!!
        # En la presente implementacion solo consideramos cuando Search indica el tipo de agente
        # Buscamos una coincidencia exacta
        # Retornamos el primero de la lista de posibilidades

        logger.info('Peticion de busqueda')
        agn_type = gm.value(subject=content, predicate=DSO.AgentType)

        rsearch = dsgraph.triples((None, DSO.AgentType, agn_type))
        if rsearch is not None:
            agn_uri = next(rsearch)[0]
            agn_add = dsgraph.value(subject=agn_uri, predicate=DSO.Address)
            agn_name = dsgraph.value(subject=agn_uri, predicate=FOAF.name)
            gr = Graph()
            gr.bind('dso', DSO)
            gr.bind('foaf',FOAF)
            rsp_obj = agn['Directory-response']

            gr.add((rsp_obj, DSO.Address, agn_add))
            gr.add((rsp_obj, DSO.Uri, agn_uri))
            gr.add((rsp_obj, FOAF.name, agn_name))
            logger.info('He encontrado a un agente')
            return build_message(gr,
                                 ACL.inform,
                                 sender=DirectoryAgent.uri,
                                 msgcnt=mss_cnt,
                                 receiver=agn_uri,
                                 content=rsp_obj)
        else:
            logger.info("sorry no match found")
            # Si no encontramos nada retornamos un inform sin contenido
            return build_message(Graph(),
                ACL.inform,
                sender=DirectoryAgent.uri,
                msgcnt=mss_cnt)
    
    def process_special_search(cp):
        """ La busqueda especial es buscar centros logisticos con codigo postal mas cercano al que nos han enviado"""
        #terminado pero los datos que necesita leer es decir los agentes centros logisticos aun tienen cp
        logger.info('Peticion de busqueda especial')
        agn_type = gm.value(subject=content, predicate=DSO.AgentType)
        rsearch = dsgraph.triples((None, DSO.AgentType, agn_type))
        minim = None
        v_min = 0
        for a, b, c in rsearch:
            agn_cp = abs(int(dsgraph.value(subject=a, predicate= ECSDIAmazon.Codigo_postal)) - int(cp))
            if minim == None or v_min > agn_cp:
               minim = a

        if minim is not None:
            gr = Graph()
            gr.bind('dso', DSO)
            gr.bind('foaf',FOAF)
            rsp_obj = agn['Directory-response']
            logger.info('He encontrado a un agente mas cercano')
            return build_message(gr,
                                 ACL.inform,
                                 sender=DirectoryAgent.uri,
                                 msgcnt=mss_cnt,
                                 receiver=minim,
                                 content=rsp_obj)
        else:
            logger.info("sorry no match found")
            # Si no encontramos nada retornamos un inform sin contenido
            return build_message(Graph(),
                ACL.inform,
                sender=DirectoryAgent.uri,
                msgcnt=mss_cnt)

    global dsgraph
    global mss_cnt
    # Extraemos el mensaje y creamos un grafo con él
    message = request.args['content']
    gm = Graph()
    gm.parse(data=message)

    msgdic = get_message_properties(gm)

    # Comprobamos que sea un mensaje FIPA ACL
    if not msgdic:
        # Si no es, respondemos que no hemos entendido el mensaje
        gr = build_message(Graph(),
            ACL['not-understood'],
            sender=DirectoryAgent.uri,
            msgcnt=mss_cnt)
    else:
        # Obtenemos la performativa
        if msgdic['performative'] != ACL.request:
            # Si no es un request, respondemos que no hemos entendido el mensaje
            gr = build_message(Graph(),
                ACL['not-understood'],
                sender=DirectoryAgent.uri,
                msgcnt=mss_cnt)
        else:
            # Extraemos el objeto del contenido que ha de ser una accion de la ontologia
            # de registro
            content = msgdic['content']
            # Averiguamos el tipo de la accion
            accion = gm.value(subject=content, predicate=RDF.type)

            # Accion de registro
            if accion == DSO.Register:
                gr = process_register()
            # Accion de busqueda
            elif accion == DSO.Search:
                gr = process_search()
            elif accion == DSO.SearchSpecial:
                #La buquedas especiales son: centros logisticos cercanos.
                cp_list = gm.objects(subject=content, predicate=ECSDIAmazon.Codigo_postal)
                cp = None
                for c in cp_list:
                    cp = c
                gr = process_special_search(cp)
            # No habia ninguna accion en el mensaje
            else:
                gr = build_message(Graph(),
                        ACL['not-understood'],
                        sender=DirectoryAgent.uri,
                        msgcnt=mss_cnt)
    mss_cnt += 1
    return gr.serialize(format='xml')


@app.route('/Info')
def info():
    """
    Entrada que da informacion sobre el agente a traves de una pagina web
    """
    global dsgraph
    global mss_cnt
    st = (dsgraph.serialize(format='turtle').decode()) # aplicamos decode por el string sale con una 'b' delante que simboliza que esta en binario
    graph_array = st.split('\n')
    return render_template('info.html', nmess=mss_cnt, len=len(graph_array),graph=graph_array)

@app.route("/Stop")
def stop():
    """
    Entrada que para el agente
    """
    tidyup()
    shutdown_server()
    return "Parando Servidor"


def tidyup():
    """
    Acciones previas a parar el agente
    """
    global cola1
    cola1.put(0)


def agentbehavior1(cola):
    """
    Behaviour que simplemente espera mensajes de una cola y los imprime
    hasta que llega un 0 a la cola
    """
    fin = False
    while not fin:
        while cola.empty():
            pass
        v = cola.get()
        if v == 0:
            print(v)
            return 0
        else:
            print(v)


if __name__ == '__main__':
    # Ponemos en marcha los behaviours como procesos
    ab1 = Process(target=agentbehavior1, args=(cola1,))
    ab1.start()

    # Ponemos en marcha el servidor Flask
    app.run(host=hostname, port=port, debug=True)

    ab1.join()
    logger.info('The End')