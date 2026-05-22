import os
import sys
import requests

def push_to_discord(file_path):
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("Error: DISCORD_WEBHOOK_URL environment variable is not set.")
        print("Please set it by running: export DISCORD_WEBHOOK_URL='your_webhook_url_here'")
        sys.exit(1)
        
    if not os.path.exists(file_path):
        print(f"Error: File '{file_path}' does not exist.")
        sys.exit(1)
        
    filename = os.path.basename(file_path)
    
    # We send a notification message and attach the file
    # This avoids Discord's 2000 character limit for large reports
    payload = {
        "content": f"📄 **New Macro Report:** {filename}"
    }
    
    with open(file_path, 'rb') as f:
        files = {
            "file": (filename, f, "text/markdown")
        }
        try:
            response = requests.post(webhook_url, data=payload, files=files)
            if response.status_code in [200, 204]:
                print(f"Successfully pushed {filename} to Discord.")
            else:
                print(f"Failed to push to Discord. Status code: {response.status_code}")
                print(response.text)
        except Exception as e:
            print(f"An error occurred while pushing to Discord: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python push_to_discord.py <file_path>")
        sys.exit(1)
        
    push_to_discord(sys.argv[1])
