import re
from pprint import pp
from urllib.parse import parse_qs, urlparse

import requests

from tools import get_formatted_size, check_url_patterns


# At the top of the file, add this array of API keys
RAPIDAPI_KEYS = [  # Original key
    "32a2334b9emsheccf86af7a32f9dp1ff1d1jsn88bc6f4a8e22",
    "39071c0d37msh39fdd1b46ed206ep1e8fbfjsn7533f7b6b524",
    "420034da52msh52ec5e8c40a5166p1b8b45jsn69ccbb4d7063",
    "5923e2793bmsh7d4f738c8a7a767p1964d5jsn557327f7ca58",
    # "",
    # "",
    # "",
    # "",
    # "",
    "f86f16718cmsh154a79748291c87p176b1cjsn768f0561526a",
    # Add more keys as needed
]

def get_urls_from_string(string: str) -> list[str]:
    """
    Extracts URLs from a given string.

    Args:
        string (str): The input string from which to extract URLs.

    Returns:
        list[str]: A list of URLs extracted from the input string. If no URLs are found, an empty list is returned.
    """
    pattern = r"(https?://\S+)"
    urls = re.findall(pattern, string)
    urls = [url for url in urls if check_url_patterns(url)]
    if not urls:
        return []
    return urls[0]


def find_between(data: str, first: str, last: str) -> str | None:
    """
    Searches for the first occurrence of the `first` string in `data`,
    and returns the text between the two strings.

    Args:
        data (str): The input string.
        first (str): The first string to search for.
        last (str): The last string to search for.

    Returns:
        str | None: The text between the two strings, or None if the
            `first` string was not found in `data`.
    """
    try:
        start = data.index(first) + len(first)
        end = data.index(last, start)
        return data[start:end]
    except ValueError:
        return None


def extract_surl_from_url(url: str) -> str | None:
    """
    Extracts the surl parameter from a given URL.

    Args:
        url (str): The URL from which to extract the surl parameter.

    Returns:
        str: The surl parameter, or False if the parameter could not be found.
    """
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    surl = query_params.get("surl", [])

    if surl:
        return surl[0]
    else:
        return False


def get_data(url: str):
    print(f"get_data function called with URL: {url}")
    
    # New API endpoint
    api_url = "https://terabox-api-production.up.railway.app/get_download"
    
    # Request payload
    payload = {"url": url}

    try:
        print(f"Making request to API...")
        response = requests.post(api_url, json=payload, timeout=20)
        print(f"Response status: {response.status_code}")
        print(f"Response content: {response.text[:200]}...")
        
        if response.status_code != 200:
            print("Request failed")
            return False
            
        # Parse response JSON
        response_data = response.json()
        
        # Check if response is successful
        if response_data.get("status") == "success":
            download_links = response_data.get("download_link", {})
            
            # Get all URLs
            url_3 = download_links.get("url_3")
            url_2 = download_links.get("url_2")
            url_1 = download_links.get("url_1")
            
            if not any([url_1, url_2, url_3]):
                print("No download links found in response")
                return False
                
            data = {
                "file_name": url.split("/")[-1] + ".mp4",  # Default filename
                "direct_link": url_3,  # Primary URL
                "backup_links": [url_1],  # Backup URLs in order
                "thumb": "",  # No thumbnail in new API
                "size": "0 B",  # Size not provided in new API
                "sizebytes": 0,  # Size not provided in new API
            }
            print(f"Successfully gathered data: {data}")
            return data
        
        print("API response indicates failure")
        return False

    except Exception as e:
        print(f"Error with API request: {e}")
        return False
