# backend/app/services/uploader.py
from googleapiclient.discovery import build
from oauth2client.file import Storage
from oauth2client.client import flow_from_clientsecrets

def get_authenticated_service():
    flow = flow_from_clientsecrets("client_secret.json", scope=[
        "https://www.googleapis.com/auth/youtube.upload"])
    storage = Storage("token.json")
    creds = storage.get()
    if not creds or creds.invalid:
        creds = flow.run_local_server(port=0)
        storage.put(creds)
    return build("youtube", "v3", credentials=creds)

def upload_clip(filepath: str, title: str, description: str, channel_id: str):
    yt = get_authenticated_service()
    body = dict(
      snippet=dict(
        title=title, description=description, tags=["highlight","auto"],
        categoryId="22"  # People & Blogs
      ),
      status=dict(privacyStatus="public")
    )
    media = MediaFileUpload(filepath, chunksize=-1, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = req.execute()
    return resp
