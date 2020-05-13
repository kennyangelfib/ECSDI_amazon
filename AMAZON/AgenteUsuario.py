# -*- coding: utf-8 -*-
"""
Nombre del fichero: AgenteGestorDeProductos

Agente que gestiona las peticiones de los usuarios


/comm es la entrada para la recepcion de mensajes del agente
/Stop es la entrada que para el agente

Tiene una funcion AgentBehavior1 que se lanza como un thread concurrente

Se que el agente de registro esta en el puerto 9000

"""
from flask import Flask, render_template, request
import socket
import argparse
from rdflib import Namespace
from AgentUtil.Agent import Agent

parser = argparse.ArgumentParser()
parser.add_argument('--open', help="Define si el servidor esta abierto al exterior o no", action='store_true', default=False)
parser.add_argument('--port', type=int, help="Puerto de comunicacion del agente")

# parsear los parametros de entrada
args = parser.parse_args()
# configurar cosas
if args.port is None:
    port = 9000
else:
    port = args.port
if args.open:
    hostname = '0.0.0.0'
else:
    hostname = socket.gethostname()
print('DS Hostname =', socket.gethostname())


#crear aplicacion servidor
app = Flask(__name__, template_folder="./templates")

#confiurar RDFuri
agn = Namespace("http://www.agentes.org#")


#crear agente
AgenteGestorDeProductos = Agent('AgenteGestorDeProductos', agn.AgenteGestorDeProductos,
                          'http://%s:%d/comm' % (hostname, port),'http://%s:%d/Stop' % (hostname, port))



@app.route("/")
def main():
    print("Entrado en main")
    return render_template("pg_usuario.html")



@app.route("/buscar", methods=["GET","POST"])
def buscar_productos():
    """
    Permite la comunicacion con el agente via un navegador, via un formulario
    """
    print("Entrado en /buscar")
    if(request == "GET"):
        return render_template("buscar.html")
    
    elif (request == "POST"):
        #buscar productos
        print()
    return "OK"

if __name__ == '__main__':
    # Ponemos en marcha el servidor Flask
    app.run(debug=True, host=hostname, port=port, use_reloader=False)