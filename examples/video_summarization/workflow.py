import io
from typing import List, Optional, Union

from pydantic import BaseModel, Field
from rich import print

from indexify import RemoteGraph
from indexify.functions_sdk.data_objects import File
from indexify.functions_sdk.graph import Graph
from indexify.functions_sdk.image import Image
from indexify.functions_sdk.indexify_functions import (
    indexify_function,
    indexify_router,
)

# Data Models
class YoutubeURL(BaseModel):
    url: str = Field(..., description="URL of the youtube video")
    resolution: str = Field("480p", description="Resolution of the video")

class SpeechSegment(BaseModel):
    speaker: Optional[str] = None
    text: str
    start_ts: float
    end_ts: float

class SpeechClassification(BaseModel):
    classification: str
    confidence: float

class Transcription(BaseModel):
    segments: List[SpeechSegment]
    classification: Optional[SpeechClassification] = None

class Summary(BaseModel):
    summary: str

# Image Definitions
yt_downloader_image = Image().name("yt-image-1").run("pip install pytubefix")
audio_image = Image().name("audio-image-1").run("pip install pydub")
transcribe_image = Image().name("transcribe-image-1").run("pip install faster_whisper")
llama_cpp_image = (
    Image()
    .name("classify-image-1")
    .run("apt-get update && apt-get install -y build-essential")
    .run("pip install llama-cpp-python")
    .run("apt-get purge -y build-essential && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*")
)

# Indexify Functions
@indexify_function(image=yt_downloader_image)
def download_youtube_video(url: YoutubeURL) -> List[File]:
    """Download the youtube video from the url."""
    from pytubefix import YouTube
    yt = YouTube(url.url)
    print("Downloading video...")
    content = yt.streams.first().download()
    print("Video downloaded")
    return [File(data=content, mime_type="video/mp4")]

@indexify_function(image=audio_image)
def extract_audio_from_video(file: File) -> File:
    """Extract the audio from the video."""
    from pydub import AudioSegment
    audio = AudioSegment.from_file(file.data)
    return File(data=audio.export("audio.wav", format="wav").read(), mime_type="audio/wav")

@indexify_function(image=transcribe_image)
def transcribe_audio(file: File) -> Transcription:
    """Transcribe audio and diarize speakers."""
    from faster_whisper import WhisperModel
    model = WhisperModel("base", device="cpu")
    segments, _ = model.transcribe(io.BytesIO(file.data))
    audio_segments = [SpeechSegment(text=segment.text, start_ts=segment.start, end_ts=segment.end) for segment in segments]
    return Transcription(segments=audio_segments)

@indexify_function(image=llama_cpp_image)
def classify_meeting_intent(speech: Transcription) -> Transcription:
    """Classify the intent of the audio."""
    from llama_cpp import Llama
    model = Llama.from_pretrained(
        repo_id="NousResearch/Hermes-3-Llama-3.1-8B-GGUF",
        filename="*Q8_0.gguf",
        verbose=True,
        n_ctx=60000,
    )
    transcription_text = "\n".join([segment.text for segment in speech.segments])
    prompt = f"""
    Classify the intent of the audio. Possible intents:
    - job-interview
    - sales-call
    - customer-support-call
    - technical-support-call
    - marketing-call
    - product-call
    - financial-call
    Format: intent: <intent>

    Transcription:
    {transcription_text}
    """
    output = model(prompt=prompt, max_tokens=50, stop=["\n"])
    response = output["choices"][0]["text"]
    print(f"response: {response}")
    intent = response.split(":")[-1].strip()
    if intent in ["job-interview", "sales-call", "customer-support-call", "technical-support-call", "marketing-call", "product-call", "financial-call"]:
        speech.classification = SpeechClassification(classification=intent, confidence=0)
    else:
        speech.classification = SpeechClassification(classification="unknown", confidence=0)
    return speech

@indexify_function(image=llama_cpp_image)
def summarize_job_interview(speech: Transcription) -> Summary:
    """Summarize the job interview."""
    from llama_cpp import Llama
    model = Llama.from_pretrained(
        repo_id="NousResearch/Hermes-3-Llama-3.1-8B-GGUF",
        filename="*Q8_0.gguf",
        verbose=True,
        n_ctx=60000,
    )
    transcription_text = "\n".join([segment.text for segment in speech.segments])
    prompt = f"""
    Summarize the key points from this job interview transcript, including:
    1. Candidate's Strengths and Qualifications
    2. Key Responses and Insights
    3. Cultural Fit and Soft Skills
    4. Areas of Concern or Improvement
    5. Overall Impression and Recommendation

    Transcript:
    {transcription_text}
    """
    output = model(prompt=prompt, max_tokens=30000, stop=["\n"])
    return Summary(summary=output["choices"][0]["text"])

@indexify_function(image=llama_cpp_image)
def summarize_sales_call(speech: Transcription) -> Summary:
    """Summarize the sales call."""
    from llama_cpp import Llama
    model = Llama.from_pretrained(
        repo_id="NousResearch/Hermes-3-Llama-3.1-8B-GGUF",
        filename="*Q8_0.gguf",
        verbose=True,
        n_ctx=60000,
    )
    transcription_text = "\n".join([segment.text for segment in speech.segments])
    prompt = f"""
    Summarize this sales call transcript, highlighting:
    - Key details
    - Client concerns
    - Action items
    - Next steps
    - Recommendations for improving the approach

    Transcript:
    {transcription_text}
    """
    output = model(prompt=prompt, max_tokens=30000, stop=["\n"])
    return Summary(summary=output["choices"][0]["text"])

@indexify_router()
def route_transcription_to_summarizer(speech: Transcription) -> List[Union[summarize_job_interview, summarize_sales_call]]:
    """Route the transcription to the appropriate summarizer based on the classification."""
    if speech.classification.classification == "job-interview":
        return summarize_job_interview
    elif speech.classification.classification in ["sales-call", "marketing-call", "product-call"]:
        return summarize_sales_call
    return None

def create_graph():
    g = Graph("Youtube_Video_Summarizer", start_node=download_youtube_video)
    g.add_edge(download_youtube_video, extract_audio_from_video)
    g.add_edge(extract_audio_from_video, transcribe_audio)
    g.add_edge(transcribe_audio, classify_meeting_intent)
    g.add_edge(classify_meeting_intent, route_transcription_to_summarizer)
    g.route(route_transcription_to_summarizer, [summarize_job_interview, summarize_sales_call])
    return g

def main():
    g = create_graph()
    remote_graph = g  # For local execution
    # remote_graph = RemoteGraph.deploy(g)  # For remote execution

    youtube_url = "https://www.youtube.com/watch?v=gjHv4pM8WEQ"
    invocation_id = remote_graph.run(block_until_done=True, url=YoutubeURL(url=youtube_url))
    
    print(f"[bold]Retrieving transcription for {invocation_id}[/bold]")
    transcription = remote_graph.output(invocation_id=invocation_id, fn_name=transcribe_audio.name)[0]
    for segment in transcription.segments:
        print(f"[bold]{round(segment.start_ts, 2)} - {round(segment.end_ts, 2)}[/bold]: {segment.text}")

    classification = remote_graph.output(invocation_id=invocation_id, fn_name=classify_meeting_intent.name)[0].classification
    print(f"[bold]Transcription Classification: {classification.classification}[/bold]")

    print("[bold]Summarization of transcription[/bold]")
    if classification.classification == "job-interview":
        summary = remote_graph.output(invocation_id=invocation_id, fn_name=summarize_job_interview.name)[0]
    elif classification.classification in ["sales-call", "marketing-call", "product-call"]:
        summary = remote_graph.output(invocation_id=invocation_id, fn_name=summarize_sales_call.name)[0]
    else:
        print("No suitable summarization found for the classification.")
        return

    print(summary.summary)

if __name__ == "__main__":
    main()
