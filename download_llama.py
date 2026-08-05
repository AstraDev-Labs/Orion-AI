import urllib.request
import json
import zipfile
import os

url = "https://api.github.com/repos/ggerganov/llama.cpp/releases/latest"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        
        assets_to_download = []
        for asset in data['assets']:
            if "win-cuda-12.4" in asset['name']:
                assets_to_download.append(asset)
                
        for asset in assets_to_download:
            download_url = asset['browser_download_url']
            print(f"Downloading {asset['name']}...")
            
            zip_path = asset['name']
            urllib.request.urlretrieve(download_url, zip_path)
            print("Extracting...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall("C:/Users/Tharun/Documents/Orion-main/llama.cpp/bin")
            os.remove(zip_path)
            print("Done with", asset['name'])
except Exception as e:
    print("Error:", e)
