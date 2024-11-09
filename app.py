from flask import Flask, request, jsonify, render_template, redirect, url_for, Response, send_file
from openai import OpenAI
import boto3
import os
from pathlib import Path
from datetime import datetime

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

# Index page to render template and display audio files
@app.route("/")
def index():
    audio_files = []
    try:
        response = s3.list_objects_v2(Bucket=bucket_name)
        for obj in response.get("Contents", []):
            audio_files.append({"name": obj["Key"], "is_image": "image" in obj["Key"], "description": ""})
    except Exception as e:
        print(f"Erro ao listar arquivos: {str(e)}")
    return render_template("index.html", audio_files=audio_files)

# Route for audio generation
@app.route("/generate-audio", methods=["POST"])
def generate_audio():
    text = request.form.get("text", "")
    filename = request.form.get("filename", f"audio_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")
    voice = request.form.get("voice", "alloy")
    model = request.form.get("model", "tts-1")

    try:
        speech_file_path = Path("/tmp") / "speech.mp3"
        response = client.audio.speech.create(model=model, voice=voice, input=text)
        response.stream_to_file(speech_file_path)
        with open(speech_file_path, "rb") as audio_file:
            audio_data = audio_file.read()

        s3.put_object(Bucket=bucket_name, Key=f"{filename}.mp3", Body=audio_data, ContentType="audio/mpeg")
    except Exception as e:
        return jsonify({"error": f"Erro ao converter texto em áudio: {str(e)}"}), 500

    return redirect(url_for("index"))

# Route for image analysis
@app.route("/analyze-image", methods=["POST"])
def analyze_image():
    image = request.files["image"]
    filename = f"image_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.jpg"

    try:
        s3.put_object(Bucket=bucket_name, Key=filename, Body=image, ContentType="image/jpeg")
        image_url = f"{os.getenv('S3_ENDPOINT_URL')}/{bucket_name}/{filename}"
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Você é um assistente de visão que analisa imagens."},
                {"role": "user", "content": [
                    {"type": "text", "text": "Descreva a imagem em detalhes."},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]}
            ]
        )
        description = response.choices[0].message["content"]
    except Exception as e:
        return jsonify({"error": f"Erro ao processar imagem: {str(e)}"}), 500

    # Save audio description
    audio_filename = f"{filename.split('.')[0]}_desc.mp3"
    try:
        audio_response = client.audio.speech.create(model="tts-1", voice="alloy", input=description)
        audio_path = Path("/tmp") / audio_filename
        audio_response.stream_to_file(audio_path)

        with open(audio_path, "rb") as audio_file:
            audio_data = audio_file.read()

        s3.put_object(Bucket=bucket_name, Key=audio_filename, Body=audio_data, ContentType="audio/mpeg")
    except Exception as e:
        return jsonify({"error": f"Erro ao gerar áudio: {str(e)}"}), 500

    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
