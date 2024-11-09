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

bucket_name = os.getenv("BUCKET_NAME")

@app.route("/")
def index():
    audio_files = []
    image_files = []
    try:
        response = s3.list_objects_v2(Bucket=bucket_name)
        for obj in response.get("Contents", []):
            if obj["Key"].endswith(".mp3"):
                audio_files.append(obj["Key"])
            elif obj["Key"].endswith((".jpg", ".jpeg", ".png")):
                image_files.append(obj["Key"])
    except Exception as e:
        print(f"Erro ao listar arquivos: {str(e)}")

    return render_template("index.html", audio_files=audio_files, image_files=image_files)

@app.route("/analyze-image", methods=["POST"])
def analyze_image():
    if "file" not in request.files:
        return jsonify({"error": "Arquivo não enviado"}), 400

    file = request.files["file"]
    filename = f"image_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.{file.filename.rsplit('.', 1)[-1]}"
    file_path = f"/tmp/{filename}"
    file.save(file_path)

    try:
        # Lê o conteúdo do arquivo de imagem e faz o upload para o bucket S3 (NooBaa)
        with open(file_path, "rb") as img_file:
            image_data = img_file.read()
        s3.put_object(Bucket=bucket_name, Key=filename, Body=image_data, ContentType="image/jpeg")

        # Usa a rota /download-audio para fornecer o link acessível para a OpenAI
        image_url = url_for("download_audio", filename=filename, _external=True)

        # Chama a API da OpenAI para análise de imagem usando a URL da rota de download
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analise e diga em detalhes o que tem nesta imagem."},
                        {"type": "image_url", "image_url": {"url": image_url}}
                    ]
                }
            ],
            max_tokens=300
        )
        analysis_text = response.choices[0].message["content"]

        # Converte o texto de análise em áudio
        speech_file_path = Path("/tmp") / "analysis_audio.mp3"
        speech_response = client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=analysis_text
        )
        speech_response.stream_to_file(speech_file_path)

        # Faz o upload do áudio resultante
        audio_filename = f"{filename.rsplit('.', 1)[0]}_analysis.mp3"
        with open(speech_file_path, "rb") as audio_file:
            s3.put_object(Bucket=bucket_name, Key=audio_filename, Body=audio_file.read(), ContentType="audio/mpeg")
    except Exception as e:
        return jsonify({"error": f"Erro na análise de imagem: {str(e)}"}), 500

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

@app.route("/delete-image/<filename>", methods=["POST"])
def delete_image(filename):
    try:
        s3.delete_object(Bucket=bucket_name, Key=filename)
        audio_filename = f"{filename.rsplit('.', 1)[0]}_analysis.mp3"
        s3.delete_object(Bucket=bucket_name, Key=audio_filename)
    except Exception as e:
        return jsonify({"error": f"Erro ao excluir imagem: {str(e)}"}), 500

    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
