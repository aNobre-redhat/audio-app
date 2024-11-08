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
