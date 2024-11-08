import os
import openai
import boto3
from flask import Flask, request, jsonify, render_template, redirect, url_for, Response
from datetime import datetime
from io import BytesIO
from pathlib import Path

app = Flask(__name__)

# Configuração da API OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Configuração do cliente S3 do NooBaa
s3 = boto3.client(
    's3',
    endpoint_url=os.getenv('S3_ENDPOINT_URL'),
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    verify=False  # Desativa a verificação de SSL para certificados autoassinados
)

# Nome do bucket S3
bucket_name = os.getenv("BUCKET_NAME")

@app.route("/")
def index():
    # Recupera a lista de áudios armazenados no bucket
    audio_files = []
    try:
        response = s3.list_objects_v2(Bucket=bucket_name)
        for obj in response.get("Contents", []):
            audio_files.append(obj["Key"])
    except Exception as e:
        print(f"Erro ao listar áudios: {str(e)}")

    return render_template("index.html", audio_files=audio_files)

@app.route("/generate-audio", methods=["POST"])
def generate_audio():
    text = request.form.get("text", "")

    if not text:
        return jsonify({"error": "Texto não fornecido"}), 400

    # Converte o texto em áudio usando o TTS da OpenAI
    try:
        speech_file_path = Path("/tmp") / "speech.mp3"
        response = client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=text
        )
        response.stream_to_file(speech_file_path)

        # Lê o conteúdo do arquivo de áudio para upload no S3
        with open(speech_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
    except Exception as e:
        return jsonify({"error": f"Erro ao converter texto em áudio: {str(e)}"}), 500

    # Cria um nome de arquivo único com timestamp
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    filename = f"audio_{timestamp}.mp3"

    # Upload do áudio para o bucket S3 (NooBaa)
    try:
        s3.put_object(
            Bucket=bucket_name,
            Key=filename,
            Body=audio_data,
            ContentType="audio/mpeg"
        )
    except Exception as e:
        return jsonify({"error": f"Erro ao fazer upload para o bucket S3: {str(e)}"}), 500

    return redirect(url_for("index"))

@app.route("/play-audio/<filename>", methods=["GET"])
def play_audio(filename):
    # Gera o conteúdo do áudio diretamente para o navegador
    try:
        audio_obj = s3.get_object(Bucket=bucket_name, Key=filename)
        return Response(
            audio_obj["Body"].read(),
            content_type="audio/mpeg",
            headers={"Content-Disposition": f'inline; filename="{filename}"'}
        )
    except Exception as e:
        return jsonify({"error": f"Erro ao obter áudio: {str(e)}"}), 500

@app.route("/delete-audio/<filename>", methods=["POST"])
def delete_audio(filename):
    # Exclui o áudio do bucket S3
    try:
        s3.delete_object(Bucket=bucket_name, Key=filename)
    except Exception as e:
        return jsonify({"error": f"Erro ao excluir áudio: {str(e)}"}), 500

    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
