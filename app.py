import os
from flask import Flask, request, jsonify, render_template, redirect, url_for, Response
from datetime import datetime
from pathlib import Path
import boto3
from openai import OpenAI

app = Flask(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

s3 = boto3.client(
    's3',
    endpoint_url=os.getenv('S3_ENDPOINT_URL'),
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    verify=False
)

bucket_name = os.getenv("BUCKET_NAME")

@app.route("/")
def index():
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
    filename = request.form.get("filename", "")
    voice = request.form.get("voice", "alloy")
    model = request.form.get("model", "tts-1")

    if not text:
        return jsonify({"error": "Texto não fornecido"}), 400

    try:
        speech_file_path = Path("/tmp") / "speech.mp3"
        response = client.audio.speech.create(
            model=model,
            voice=voice,
            input=text
        )
        response.stream_to_file(speech_file_path)
        with open(speech_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
    except Exception as e:
        return jsonify({"error": f"Erro ao converter texto em áudio: {str(e)}"}), 500

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    if not filename:
        filename = f"audio_{timestamp}"
    filename = f"{filename}.mp3"

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

@app.route("/analyze-image", methods=["POST"])
def analyze_image():
    if "image" not in request.files:
        return jsonify({"error": "Nenhuma imagem enviada"}), 400
    image = request.files["image"]

    if image.filename == "":
        return jsonify({"error": "Arquivo de imagem inválido"}), 400

    try:
        file_path = Path("/tmp") / image.filename
        image.save(file_path)

        with open(file_path, "rb") as img:
            image_data = img.read()

        s3.put_object(Bucket=bucket_name, Key=image.filename, Body=image_data, ContentType="image/jpeg")

        image_url = f"{s3.meta.endpoint_url}/{bucket_name}/{image.filename}"

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": "Descreva a imagem em detalhes."},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]}
            ],
            max_tokens=300
        )

        description = response.choices[0].message["content"]

        return render_template("index.html", description=description)

    except Exception as e:
        return jsonify({"error": f"Erro ao analisar imagem: {str(e)}"}), 500
