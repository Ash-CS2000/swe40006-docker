from flask import Flask
import socket
import platform

app = Flask(__name__)

@app.route("/")
def hello():
    return f"""
    <h1>Hello World from Docker!</h1>
    <p>SWE40006 Task 4.2 - Aung Si Hein</p>
    <p>Container hostname: {socket.gethostname()}</p>
    <p>Architecture: {platform.machine()}</p>
    """

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)