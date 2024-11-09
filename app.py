import os
from flask import Flask, request, jsonify, render_template, redirect, url_for, Response
from datetime import datetime
from pathlib import Path
import boto3
import openai
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Configuração da API OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")
client = openai.OpenAI()  # Inicializa o cliente

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
    # Recupera a lista de áudios e imagens armazenados no bucket
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
    voice = request.form.get("voice", "alloy")
    filename = request.form.get("filename", f"audio_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.mp3")

    if not text:
        return jsonify({"error": "Texto não fornecido"}), 400

    # Geração de áudio a partir do texto
    try:
        audio_file_path = Path("/tmp") / filename
        tts_response = client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text
        )
        tts_response.stream_to_file(audio_file_path)

        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
    except Exception as e:
        return jsonify({"error": f"Erro ao gerar áudio: {str(e)}"}), 500

    # Upload do áudio para o S3
    try:
        s3.put_object(Bucket=bucket_name, Key=filename, Body=audio_data, ContentType="audio/mpeg")
    except Exception as e:
        return jsonify({"error": f"Erro ao fazer upload para o bucket S3: {str(e)}"}), 500

    return redirect(url_for("index"))

@app.route("/upload-image", methods=["POST"])
def upload_image():
    if 'image' not in request.files:
        return jsonify({"error": "Nenhuma imagem enviada"}), 400
    
    image = request.files['image']
    if image.filename == '':
        return jsonify({"error": "Nenhuma imagem selecionada"}), 400
    
    filename = secure_filename(image.filename)
    image_path = Path("/tmp") / filename
    image.save(image_path)

    # Upload da imagem para S3 e geração de URL correta
    try:
        s3.put_object(Bucket=bucket_name, Key=filename, Body=open(image_path, "rb"), ContentType="image/jpeg")
        endpoint_url = os.getenv('S3_ENDPOINT_URL').rstrip('/')  # Remove a barra final se houver
        image_url = f"{endpoint_url}/{bucket_name}/{filename}"  # Concatena URL corretamente
    except Exception as e:
        return jsonify({"error": f"Erro ao fazer upload da imagem para o S3: {str(e)}"}), 500

    # Análise da imagem usando o modelo de visão
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Descreva a imagem em detalhes, para ser lida para uma criança entender o que tem na imagem."},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url}
                        },
                    ],
                }
            ],
            max_tokens=300,
        )
        description = response['choices'][0]['message']['content']
    except Exception as e:
        return jsonify({"error": f"Erro ao analisar imagem: {str(e)}"}), 500

    # Geração de áudio a partir da descrição
    try:
        audio_file_path = Path("/tmp") / f"{filename}_description.mp3"
        tts_response = client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=description
        )
        tts_response.stream_to_file(audio_file_path)

        with open(audio_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
    except Exception as e:
        return jsonify({"error": f"Erro ao gerar áudio: {str(e)}"}), 500

    # Salvar o áudio no S3
    try:
        s3.put_object(Bucket=bucket_name, Key=f"{filename}_description.mp3", Body=audio_data, ContentType="audio/mpeg")
    except Exception as e:
        return jsonify({"error": f"Erro ao fazer upload do áudio para o bucket S3: {str(e)}"}), 500

    return redirect(url_for("index"))

@app.route("/download/<filename>", methods=["GET"])
def download(filename):
    try:
        file_obj = s3.get_object(Bucket=bucket_name, Key=filename)
        return Response(
            file_obj["Body"].read(),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        return jsonify({"error": f"Erro ao baixar arquivo: {str(e)}"}), 500

@app.route("/play-audio/<filename>", methods=["GET"])
def play_audio(filename):
    try:
        audio_obj = s3.get_object(Bucket=bucket_name, Key=filename)
        return Response(
            audio_obj["Body"].read(),
            content_type="audio/mpeg",
            headers={"Content-Disposition": f'inline; filename="{filename}"'}
        )
    except Exception as e:
        return jsonify({"error": f"Erro ao obter áudio: {str(e)}"}), 500

@app.route("/delete_file/<filename>", methods=["POST"])
def delete_file(filename):
    try:
        s3.delete_object(Bucket=bucket_name, Key=filename)
    except Exception as e:
        return jsonify({"error": f"Erro ao excluir o arquivo: {str(e)}"}), 500
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
