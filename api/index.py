from http.server import BaseHTTPRequestHandler
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json
import os

app = FastAPI()

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ruta raíz que redirige al frontend
@app.get("/")
async def root():
    return {"message": "Bienvenido a la API de Discord Extractor. Por favor, usa el frontend para interactuar con la aplicación."}

# Ruta para manejar las solicitudes de la API
def handler(req, context):
    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
        },
        'body': json.dumps({'message': 'Hola desde la API de Vercel!'})
    }

# Si se ejecuta localmente
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
