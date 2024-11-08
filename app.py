import os
import openai
import boto3
from flask import Flask, request, jsonify, render_template, redirect, url_for
from datetime import datetime
from io import BytesIO
from pathlib import Path

app = Flask(__name__)

# Configuração da API OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# Configuração do cliente S3 do NooBaa
s3 = boto3.client(
    's3',
    endpoint_url=os.getenv('S3_ENDPOINT_URL'),
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    verify=True  # SSL ativado para o endpoint HTTPS
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

    # Gera o texto usando o modelo GPT-4
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Você é um assistente para Text To Speech. O texto que você receber vamos converter em audio, por isso preste atenção na pontuação e gramática para gerar as emoções."},
                {"role": "user", "content": text}
            ]
        )
        generated_text = response.choices[0].message['content'].strip()
    except Exception as e:
        return jsonify({"error": f"Erro ao gerar texto com GPT-4: {str(e)}"}), 500

    # Converte o texto em áudio usando o TTS da OpenAI
    try:
        # Cria um caminho temporário para salvar o arquivo de áudio
        speech_file_path = Path("/tmp") / "speech.mp3"
        audio_response = openai.Audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=generated_text
        )
        
        # Salva o áudio no caminho temporário
        audio_response.stream_to_file(speech_file_path)

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
    # Gera uma URL de download temporária para o arquivo no bucket S3
    try:
        url = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket_name, 'Key': filename},
            ExpiresIn=3600  # URL expira em 1 hora
        )
    except Exception as e:
        return jsonify({"error": f"Erro ao gerar URL: {str(e)}"}), 500

    return redirect(url)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
