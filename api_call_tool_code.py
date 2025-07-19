import requests
import json

def run(params: dict, config: dict) -> dict:
    """
    Executes an API call with the given parameters.

    Args:
        params (dict): A dictionary containing the necessary parameters.
            - url (str): The URL of the API endpoint.
            - method (str): The HTTP method (GET, POST, PUT, DELETE, PATCH).
            - headers (str, optional): A JSON string representing the request headers.
            - body (str, optional): A JSON string representing the request body.
        config (dict): A dictionary for configuration (e.g., db session), not used here.

    Returns:
        A dictionary containing the status code and response data or an error message.
    """
    url = params.get("url")
    method = params.get("method")
    headers_str = params.get("headers", "{}")
    body_str = params.get("body", "{}")

    if not url or not method:
        return {"error": "API Call tool requires 'url' and 'method' parameters."}

    try:
        parsed_headers = json.loads(headers_str) if headers_str else {}
        
        # Only parse body for methods that typically have one
        parsed_body = {}
        if method.upper() in ["POST", "PUT", "PATCH"] and body_str:
            parsed_body = json.loads(body_str)

        response = requests.request(
            method=method.upper(),
            url=url,
            headers=parsed_headers,
            json=parsed_body,
            timeout=30  # Add a timeout for good practice
        )

        # Raise an exception for bad status codes (4xx or 5xx)
        response.raise_for_status()

        # Try to parse the response as JSON, fall back to text
        try:
            response_data = response.json()
        except json.JSONDecodeError:
            response_data = response.text

        return {
            "status_code": response.status_code,
            "response": response_data
        }

    except requests.exceptions.RequestException as e:
        return {
            "status_code": e.response.status_code if e.response else 500,
            "error": str(e)
        }
    except json.JSONDecodeError as e:
        return {
            "status_code": 400,
            "error": f"Invalid JSON format in headers or body: {str(e)}"
        }
    except Exception as e:
        return {
            "status_code": 500,
            "error": f"An unexpected error occurred: {str(e)}"
        }
