import os
from flask import Flask, request, jsonify, render_template, redirect, url_for, Response
from datetime import datetime
from pathlib import Path
import boto3
from openai import OpenAI

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
    filename = request.form.get("filename", "")
    voice = request.form.get("voice", "alloy")  # Valor padrão caso não seja enviado
    model = request.form.get("model", "tts-1")  # Valor padrão caso não seja enviado

    if not text:
        return jsonify({"error": "Texto não fornecido"}), 400

    # Converte o texto em áudio usando o TTS da OpenAI com o modelo e voz selecionados
    try:
        speech_file_path = Path("/tmp") / "speech.mp3"
        response = client.audio.speech.create(
            model=model,  # Modelo selecionado
            voice=voice,  # Voz selecionada
            input=text
        )
        response.stream_to_file(speech_file_path)

        # Lê o conteúdo do arquivo de áudio para upload no S3
        with open(speech_file_path, "rb") as audio_file:
            audio_data = audio_file.read()
    except Exception as e:
        return jsonify({"error": f"Erro ao converter texto em áudio: {str(e)}"}), 500

    # Define o nome do arquivo ou usa o timestamp como fallback
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    if not filename:
        filename = f"audio_{timestamp}"
    filename = f"{filename}.mp3"

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

@app.route("/generate-image-audio", methods=["POST"])
def generate_image_audio():
    # Lê a imagem do upload
    image = request.files.get("image")
    if not image:
        return jsonify({"error": "Imagem não fornecida"}), 400

    # Salva a imagem temporariamente
    image_path = Path("/tmp") / image.filename
    image.save(image_path)

    try:
        # URL da imagem para o bucket S3
        s3.upload_file(
            str(image_path), bucket_name, image.filename, ExtraArgs={"ContentType": "image/jpeg"}
        )
        image_url = f"{os.getenv('S3_ENDPOINT_URL')}/{bucket_name}/{image.filename}"

        # Gera a descrição usando o GPT-4 vision
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": "Descreva a imagem em detalhes"},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]}
            ]
        )
        description = response.choices[0].message["content"]

        # Converte a descrição em áudio
        audio_response = client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=description
        )
        audio_path = Path("/tmp") / "description.mp3"
        audio_response.stream_to_file(audio_path)

        # Upload do áudio
        audio_filename = f"description_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.mp3"
        with open(audio_path, "rb") as audio_file:
            s3.put_object(
                Bucket=bucket_name,
                Key=audio_filename,
                Body=audio_file.read(),
                ContentType="audio/mpeg"
            )

    except Exception as e:
        return jsonify({"error": f"Erro ao processar imagem: {str(e)}"}), 500

    return redirect(url_for("index"))

@app.route("/download-audio/<filename>", methods=["GET"])
def download_audio(filename):
    try:
        audio_obj = s3.get_object(Bucket=bucket_name, Key=filename)
        return Response(
            audio_obj["Body"].read(),
            content_type="audio/mpeg",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        return jsonify({"error": f"Erro ao baixar áudio: {str(e)}"}), 500

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

@app.route("/delete-audio/<filename>", methods=["POST"])
def delete_audio(filename):
    try:
        s3.delete_object(Bucket=bucket_name, Key=filename)
    except Exception as e:
        return jsonify({"error": f"Erro ao excluir áudio: {str(e)}"}), 500

    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
