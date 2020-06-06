import argparse
import socket
import sys
from multiprocessing import Queue, Process
from threading import Thread

from flask import Flask, request
from rdflib import Namespace, Graph, RDF, URIRef, Literal, XSD
from AgentUtil.ACLMessages import get_agent_info, send_message, build_message, get_message_properties, register_agent,get_Neareast_Logistic_Center_info
from AgentUtil.Agent import Agent
from AgentUtil.FlaskServer import shutdown_server
from AgentUtil.Logging import config_logger
from AgentUtil.OntoNamespaces import ECSDIAmazon, ACL, DSO
from rdflib.namespace import RDF, FOAF
from string import Template
import uuid
from datetime import datetime,timedelta


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
def calcularprobablefechadeenvio(prioridad):
    """Calcula el dia aproximado de envio apartir de la prioridad(1-10),ahora es un factor de 1 y sumando 1dia extra"""
    p = int(prioridad)
    x = datetime.now() + timedelta(days= (p*1)+ 1) 
    return x.strftime("%Y-%m-%d") 
#en proceso
def registrarVenta(grafo):
    """ Funcion que registra la venta realizada a la base de datos"""
    logger.info("Registrando la venta")
    print("----------------------------------------")
    print(grafo.serialize(format="xml"))
    
    venta_id = uuid.uuid4()
    direccion = ciudad = ""
    tarjeta = prioridad = codigo_postal = 0
    id_productos = []

    for s,p,o in grafo:
        if str(p) == ECSDIAmazon + "Tarjeta":
            tarjeta = str(o)
        elif str(p) == ECSDIAmazon + "Prioridad":
            prioridad = str(o)
        elif str(p) == ECSDIAmazon + "Direccion":
            direccion = str(o)
        elif str(p) == ECSDIAmazon + "Ciudad":
            ciudad = str(o)
        elif str(p) == ECSDIAmazon + "Codigo_postal":
            codigo_postal = str(o)
        elif str(p) == ECSDIAmazon + "Id_producto":
            id_productos.append(str(o))
    
    logger.info("Imprimiendo paramteros de venta")
    print(venta_id, "tarjeta: " , tarjeta, "prioridad: ", prioridad, "direccion: ", direccion, "ciudad: ", 
    ciudad, "cd_postal: ", codigo_postal)

    venta = Graph()
    venta.parse("./rdf/ventas.rdf")

    nueva_venta = ECSDIAmazon.__getattr__(str(venta_id))
    venta.add((nueva_venta, RDF.type, Literal(ECSDIAmazon + "venta")))
    venta.add((nueva_venta, ECSDIAmazon.Venta_id, Literal(venta_id)))
    venta.add((nueva_venta, ECSDIAmazon.Tarjeta, Literal(tarjeta)))
    venta.add((nueva_venta, ECSDIAmazon.Prioridad, Literal(prioridad)))
    venta.add((nueva_venta, ECSDIAmazon.Direccion, Literal(direccion)))
    venta.add((nueva_venta, ECSDIAmazon.Ciudad, Literal(ciudad)))
    venta.add((nueva_venta, ECSDIAmazon.Codigo_postal, Literal(codigo_postal)))
    venta.add((nueva_venta, ECSDIAmazon.Productos_id, Literal(id_productos)))
    
    logger.info("Escribiendo en la BD")
    venta.serialize("./rdf/ventas.rdf")
    logger.info("Registro de venta finalizado")
    return venta_id

#en proceso
def cobroVenta(precio_quasi_total,precio_envio,tarjeta):
    """Se comunica con el agente financiero para que realice el cobro""" 
    agente_financiero = get_agent_info(agn.AgenteFinanciero, DirectoryAgent, AgenteGestorDeVentas, get_message_count())
    logger.info("Enviando peticion de cobro al AgenteFinanciero")
    print("La informacion del agente financiero es:")
    print(agente_financiero.name)
    print(agente_financiero.address)
    print(agente_financiero.uri)
    grafo_transaccion = Graph()
    precio_total_final = precio_quasi_total + precio_envio
    contenido = ECSDIAmazon["Transferencia_cobro"+ str(get_message_count())]
    grafo_transaccion.add((contenido, RDF.type, ECSDIAmazon.Transferencia_cobrar))
    grafo_transaccion.add((contenido, ECSDIAmazon.Tarjeta, Literal(tarjeta, datatype=XSD.int)))
    grafo_transaccion.add((contenido, ECSDIAmazon.Precio_total, Literal(precio_total_final, datatype=XSD.int)))
    # Cobro al usuario
    respuesta_cobro = send_message(build_message(
            grafo_transaccion, perf=ACL.request, sender=AgenteGestorDeVentas.uri, receiver=agente_financiero.uri, msgcnt=get_message_count(), 
            content=contenido), agente_financiero.address)
    
    rpt = respuesta_cobro.value(predicate=ECSDIAmazon.Tranferencia)
    if rpt == "Exitosa":
        logger.info("Se ha cobrado la venta exitosamente")
        mensaje = "Se ha cobrado a su cuenta"
    else:
        logger.info("No se ha podido cobrar la venta exitosamente")
        mensaje = "Ohoh no se ha podido cobrar a el precio de la venta "
    
    # Pago a vendedor externo    
    # respuesta_pago = send_message(build_message(
    #         grafo_transaccion, perf=ACL.request, sender=AgenteGestorDeVentas.uri, receiver=agente_financiero.uri, msgcnt=get_message_count(), 
    #         content=contenido), agente_financiero.address)
    #
    
    # Datos relevantes a(suponemos que solo hay un agente usuario) del cobro al vendedor externo(solo un vendedor externo)
    grafo_transaccion = Graph()
    contenido = ECSDIAmazon["Informar"+ str(get_message_count())]
    grafo_transaccion.add((contenido, RDF.type, ECSDIAmazon.Informar))
    grafo_transaccion.add((contenido, ECSDIAmazon.Tarjeta, Literal(tarjeta, datatype=XSD.int)))
    grafo_transaccion.add((contenido, ECSDIAmazon.Precio_total, Literal(precio_total_final, datatype=XSD.float)))
    grafo_transaccion.add((contenido, ECSDIAmazon.Mensaje, Literal(mensaje, datatype=XSD.string)))

    return grafo_transaccion


#en proceso
def enviarVenta(grafo):
    '''Se encarga de enviar asignar el encargo de envio al centro logistico mas cercano al codigo postal'''
    logger.info("Obteniendo el centro logistico mas cercano al lugar de envio mediante el codigo postal")
    #Obtener el agente mas cercano
    # centrologistico = get_Neareast_Logistic_Center_info(agn.AgenteCentroLogistico, DirectoryAgent, AgenteGestorDeVentas, get_message_count(),int(codepostal))       
    centrologistico = get_agent_info(agn.AgenteCL, DirectoryAgent, AgenteGestorDeVentas, get_message_count())       

    #Reusamos el contenido del grafo antiguo para que se convierta en uno de tipo Encargo_envio
    logger.info("Haciendo peticion envio")
    grafo.remove((contenido, RDF.type, ECSDIAmazon.Iniciar_venta))
    sujeto = ECSDIAmazon['Encargo_envio' + str(get_message_count())]
    grafo.add((sujeto, RDF.type, ECSDIAmazon.Encargo_envio))

    for a, b, c in grafo:
        if a == contenido:
            grafo.remove((a, b, c))
            grafo.add((sujeto, b, c))
    #####
    
    logger.info("Informando de encargo de envio a centro logistico")
    msg_respuesta = send_message(build_message(
                                grafo, perf=ACL.request, sender=AgenteGestorDeVentas.uri,receiver=centrologistico.uri,msgcnt=get_message_count(), content=sujeto)
                                , centrologistico.address)
    logger.info("El encargo de envio que ha sido enviado")
    respuesta = msg_respuesta.value(predicate=RDF.type, object=ECSDIAmazon.Respuesta)
    if "Enviado" == msg_respuesta.value(subject=respuesta, predicate=ECSDIAmazon.Mensaje):
        logger.info("Se prodece al cobro")
        fecha_final = msg_respuesta.value(subject=respuesta, predicate=ECSDIAmazon.Fecha_final)
        transportista_asignado = msg_respuesta.value(subject=respuesta, predicate=ECSDIAmazon.Transportista_asignado)
        precio_envio = msg_respuesta.value(subject=respuesta, predicate=ECSDIAmazon.Precio_envio)
        precio_quasi_total = grafo.value(subject=sujeto, predicate=ECSDIAmazon.Precio_total)
        tarjeta = grafo.value(subject=sujeto, predicate=ECSDIAmazon.Tarjeta)
        grafinforme = cobroVenta(precio_quasi_total,precio_envio,tarjeta)
        informe=grafinforme.value(predicate=RDF.type, object=ECSDIAmazon.Informe)
        #esta parte comentada ya esta en el grafoinforme
        # grafinforme.add((contenido, ECSDIAmazon.Tarjeta, Literal(tarjeta, datatype=XSD.int)))
        # grafinforme.add((contenido, ECSDIAmazon.Precio_total, Literal(preciototal, datatype=XSD.float)))
        # grafinforme.add((contenido, ECSDIAmazon.message, Literal(message, datatype=XSD.string)))
        
        grafinforme.add((informe, ECSDIAmazon.Precio_envio, Literal(precio_envio, datatype=XSD.float)))
        grafinforme.add((informe, ECSDIAmazon.Precio_venta, Literal(precio_quasi_total, datatype=XSD.float)))
        grafinforme.add((informe, ECSDIAmazon.Fecha_final, Literal(fecha_final, datatype=XSD.date)))
        grafinforme.add((informe, ECSDIAmazon.Transportista_asignado, Literal(transportista_asignado, datatype=XSD.float)))
        
        ##Queda informar al usuario de que se le ha cobrado(total_final y precio_venta y precio_envio) por que el envio ya se ha realizado con la 
        # fecha final de llegada,el transportista asignado, total
        idventa = grafo.value(subject=sujeto, predicate=ECSDIAmazon.Id_venta)
        grafinforme.add((informe, ECSDIAmazon.Id_venta, Literal(idventa, datatype=XSD.int)))
        logger.info("Se informa al usuario que el cobro ha sido efectuado al cobro y que ya se ha enviado la venta con id"+str(idventa))
        agente_usuario = get_agent_info(agn.AgenteUsuario, DirectoryAgent, AgenteGestorDeVentas, get_message_count())
        msg_respuesta_user = send_message(build_message(
                                grafinforme, perf=ACL.request, sender=AgenteGestorDeVentas.uri,receiver=agente_usuario.uri,msgcnt=get_message_count(), contenido=informe)
                                , agente_usuario.address)
        respuesta_user= msg_respuesta_user.value(predicate=RDF.type, object=ECSDIAmazon.Respuesta)

        if "OK" == msg_respuesta_user.value(subject=respuesta_user, predicate=ECSDIAmazon.Mensaje):
            logger.info("La venta y el envio de esta han sido exitosos")
        else:
            logger.info("No se esperaba esta respuesta del usuario al enviarle el informe")    
    else:
        logger.info("No se esperaba esta respuesta del centro logistico")


def vender_productos(contenido, grafo):
    """Funcion que efectua el proceso de venta, distribuyendo la responsabilidad de distribucion a un thread"""
    
    logger.info("Peticion de venta recibida")
    idventa = registrarVenta(grafo)
    grafo.add((contenido, ECSDIAmazon.Id_venta, Literal(idventa, datatype=XSD.int)))
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

        print("antes: ", precio_total)    
        precioProducto = grafo.value(subject=producto, predicate=ECSDIAmazon.Precio_producto)
        print("precio cogido del grafo: ", float(precioProducto))
        grafo_factura.add((producto, ECSDIAmazon.Precio_producto, Literal(float(precioProducto), datatype=XSD.float)))
        precio_total += float(precioProducto)
        print("despues:", precio_total)

        grafo_factura.add((nueva_factura, ECSDIAmazon.FormadaPor, URIRef(producto)))
    
    prioridad = grafo.value(subject=contenido,predicate=ECSDIAmazon.Prioridad)
    grafo_factura.add((nueva_factura, ECSDIAmazon.Fecha_aproximada, Literal(calcularprobablefechadeenvio(prioridad), datatype=XSD.string)))
    grafo_factura.add((nueva_factura, ECSDIAmazon.Precio_total, Literal(precio_total, datatype=XSD.float)))
    grafo_factura.add((nueva_factura, ECSDIAmazon.Id_venta, Literal(idventa, datatype=XSD.int)))

    #Es estrictamente necesario la siguiente parte por que ya ponemos el precio_total al grafo ya que sera usado por el metodo enviarVenta
    ini_venta = grafo.value(predicate=RDF.type, object=ECSDIAmazon.Iniciar_venta)
    grafo.add((ini_venta, ECSDIAmazon.Precio_total, Literal(precio_total, datatype=XSD.float)))

    # Enviar encargo de envio al Centro logistico
    thread = Thread(target=enviarVenta, args=(contenido,grafo))
    thread.start()
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
                                                  sender=AgenteGestorDeVentas.uri, msgcnt=get_message_count())
        else:
            #Extraemos el contenido que ha de ser una accion de la ontologia 
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