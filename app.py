import os
import boto3
from flask import Flask, request, jsonify
import openai
from datetime import datetime

# Inicialize o Flask
app = Flask(__name__)

# Configuração da API OpenAI usando variável de ambiente para a chave de API
openai.api_key = os.getenv("OPENAI_API_KEY")

# Configuração do cliente S3 do NooBaa usando variáveis de ambiente
s3 = boto3.client(
    's3',
    endpoint_url=os.getenv('S3_ENDPOINT_URL'),  # URL do endpoint S3 (NooBaa)
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),  # Access Key ID do Secret
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),  # Secret Access Key do Secret
    verify=True  # SSL ativado para o endpoint HTTPS
)

# Nome do bucket S3 definido como variável de ambiente no Deployment
bucket_name = os.getenv("BUCKET_NAME")

@app.route("/generate-audio", methods=["POST"])
def generate_audio():
    data = request.json
    text = data.get("text", "")

    if not text:
        return jsonify({"error": "Texto não fornecido"}), 400

    # Gera o áudio usando a API do Whisper da OpenAI
    try:
        response = openai.Audio.create(
            text=text,
            model="whisper-1"
        )
        audio_content = response["data"]
    except Exception as e:
        return jsonify({"error": f"Erro ao gerar áudio: {str(e)}"}), 500

    # Cria um nome de arquivo único com timestamp
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"audio_{timestamp}.mp3"

    # Upload do áudio para o bucket S3 (NooBaa)
    try:
        s3.put_object(
            Bucket=bucket_name,
            Key=filename,
            Body=audio_content
        )
    except Exception as e:
        return jsonify({"error": f"Erro ao fazer upload para o bucket S3: {str(e)}"}), 500

    return jsonify({"message": "Áudio gerado e armazenado", "filename": filename})

@app.route("/play-audio/<filename>", methods=["GET"])
def play_audio(filename):
    # Gera uma URL de download temporária para o arquivo no bucket S3
    try:
        url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': filename},
            ExpiresIn=3600  # URL expira em 1 hora
        )
    except Exception as e:
        return jsonify({"error": f"Erro ao gerar URL: {str(e)}"}), 500

    return jsonify({"url": url})

# Para desenvolvimento local
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
