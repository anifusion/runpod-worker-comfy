import runpod
from runpod.serverless.utils import rp_upload
import json
import urllib.error
import urllib.request
import urllib.parse
import time
import os
import requests
import base64
import traceback
import re
from itertools import islice
from io import BytesIO

# Time to wait between API check attempts in milliseconds
COMFY_API_AVAILABLE_INTERVAL_MS = 50
# Maximum number of API check attempts
COMFY_API_AVAILABLE_MAX_RETRIES = 500
# Time to wait between poll attempts in milliseconds
COMFY_POLLING_INTERVAL_MS = int(os.environ.get("COMFY_POLLING_INTERVAL_MS", 250))
# Maximum number of poll attempts
COMFY_POLLING_MAX_RETRIES = int(os.environ.get("COMFY_POLLING_MAX_RETRIES", 500))
# Host where ComfyUI is running
COMFY_HOST = "127.0.0.1:8188"
# Enforce a clean state after each job is done
# see https://docs.runpod.io/docs/handler-additional-controls#refresh-worker
REFRESH_WORKER = os.environ.get("REFRESH_WORKER", "false").lower() == "true"

# Logged once per worker process after Comfy responds; shows up in Runpod logs / job output.
_NODE_DIAGNOSTICS_LOGGED = False


def _emit_diagnostic(fields, *, failure=False):
    if failure:
        try:
            stage = fields.get("stage") if isinstance(fields, dict) else None
            safe_event = {
                "event": "worker_failure",
                "stage": stage if isinstance(stage, str) and re.fullmatch(r"[a-z_]{1,40}", stage) else "unknown",
            }
            job_id = fields.get("job_id")
            if isinstance(job_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
                safe_event["job_id"] = job_id
            status = fields.get("status")
            if isinstance(status, int) and 100 <= status <= 599:
                safe_event["status"] = status
            print("runpod-worker-comfy: safe_event " + json.dumps(safe_event, ensure_ascii=True))
        except Exception:
            print('runpod-worker-comfy: safe_event {"event":"worker_failure","stage":"unknown"}')
    try:
        logged_fields = dict(fields)
        for key in ("message", "cause_message", "provider_message"):
            value = logged_fields.get(key)
            if isinstance(value, str) and len(value) > 2000:
                logged_fields[key] = value[-2000:]
                logged_fields[key + "_chars"] = len(value)
        print("runpod-worker-comfy - handler error " + json.dumps(logged_fields, ensure_ascii=True))
    except Exception:
        stage = fields.get("stage") if isinstance(fields, dict) else None
        safe_stage = stage if isinstance(stage, str) and re.fullmatch(r"[a-z_]{1,40}", stage) else "unknown"
        job_id = fields.get("job_id") if isinstance(fields, dict) else None
        safe_job_id = job_id if isinstance(job_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id) else None
        print(f"runpod-worker-comfy - handler error stage={safe_stage}" + (f" job_id={safe_job_id}" if safe_job_id else ""))


def _log_handler_error(stage, error, job_id=None):
    """Return bounded exception details for restricted worker and app logs."""
    try:
        frames = traceback.extract_tb(error.__traceback__)[-6:]
        diagnostic = {
            "stage": stage,
            "type": type(error).__name__,
            "message": str(error)[:16000],
            "frames": [f"{frame.name}:{frame.lineno}" for frame in frames],
        }
        if isinstance(job_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
            diagnostic["job_id"] = job_id
        try:
            cause = error.__cause__ or error.__context__
            if isinstance(cause, BaseException) and cause is not error:
                diagnostic["cause_type"] = type(cause).__name__
                diagnostic["cause_message"] = str(cause)[:8000]
        except Exception:
            pass
        _emit_diagnostic(diagnostic, failure=True)
        return diagnostic
    except Exception:
        try:
            diagnostic = {"stage": stage, "job_id": job_id}
            _emit_diagnostic(diagnostic, failure=True)
            return diagnostic
        except Exception:
            return {"stage": stage}


def _log_comfy_failure(stage, detail=None, status=None, job_id=None, code=None):
    diagnostic = {"stage": stage, "type": "ComfyUIError"}
    if isinstance(job_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
        diagnostic["job_id"] = job_id
    if isinstance(status, int) and 100 <= status <= 599:
        diagnostic["status"] = status
    if isinstance(code, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,79}", code):
        diagnostic["code"] = code
    if isinstance(detail, str):
        diagnostic["provider_message"] = detail[:16000]
    _emit_diagnostic(diagnostic, failure=True)
    return diagnostic


def _log_credential_failure(stage, error, job_id=None):
    diagnostic = {"stage": stage, "type": type(error).__name__[:80]}
    if isinstance(job_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", job_id):
        diagnostic["job_id"] = job_id
    try:
        response = getattr(error, "response", None)
        metadata = response.get("ResponseMetadata") if isinstance(response, dict) else None
        if isinstance(metadata, dict):
            status = metadata.get("HTTPStatusCode")
            if isinstance(status, int) and 100 <= status <= 599:
                diagnostic["status"] = status
            request_id = metadata.get("RequestId")
            if isinstance(request_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{6,128}", request_id):
                diagnostic["provider_request_id"] = request_id
    except Exception:
        pass
    _emit_diagnostic(diagnostic, failure=True)
    return diagnostic

# Nodes required by the character-sheet workflow (MVAdapter + Impact Pack + core).
_CHARACTER_SHEET_NODE_TYPES = (
    "LdmPipelineLoader",
    "DiffusersMVSchedulerLoader",
    "DiffusersMVModelMakeup",
    "DiffusersMVSampler",
    "FaceDetailer",
    "UltralyticsDetectorProvider",
)


def log_comfy_node_registry_once():
    """
    Query ComfyUI /object_info once and print whether critical custom nodes registered.
    If MVAdapter fails to import, these types are absent even when the directory exists on disk.
    """
    global _NODE_DIAGNOSTICS_LOGGED
    if _NODE_DIAGNOSTICS_LOGGED:
        return
    _NODE_DIAGNOSTICS_LOGGED = True
    url = f"http://{COMFY_HOST}/object_info"
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            print(f"runpod-worker-comfy - object_info: unexpected JSON type {type(data)}")
            return
        print(
            f"runpod-worker-comfy - object_info: {len(data)} node type(s) registered"
        )
        for name in _CHARACTER_SHEET_NODE_TYPES:
            status = "PRESENT" if name in data else "MISSING"
            print(f"runpod-worker-comfy - object_info node {name!r}: {status}")
        missing = [n for n in _CHARACTER_SHEET_NODE_TYPES if n not in data]
        if missing:
            print(
                "runpod-worker-comfy - HINT: Check Comfy stderr above. Common fixes: (1) cv2/libgthread "
                "error → image needs apt package libglib2.0-0. (2) SCHEDULER_HANDLERS → Impact Pack "
                "must be tag 8.9 with ComfyUI 0.2.7, not Main. (3) UltralyticsDetectorProvider → "
                "ComfyUI-Impact-Subpack. (4) App workflow must use MVAdapter v1.0.2 API names "
                "DiffusersMVSchedulerLoader / DiffusersMVModelMakeup (not DiffusersSchedulerLoader). "
                "(5) numpy<2 for Impact 8.x after MVAdapter pip."
            )
    except requests.RequestException:
        _emit_diagnostic({"stage": "object_info_probe", "type": "ProviderRequestError"})


def _format_comfy_prompt_error(body: dict) -> str:
    """Keep bounded provider text in restricted worker diagnostics."""
    err = body.get("error")
    parts = []
    if isinstance(err, dict):
        parts.extend(value[:8000] for value in (err.get("type"), err.get("message"), err.get("details"))
                     if isinstance(value, str))
    elif isinstance(err, str):
        parts.append(err[:16000])
    node_errors = body.get("node_errors")
    if isinstance(node_errors, dict):
        parts.append(f"Node validation failed for {min(len(node_errors), 999)} node(s)")
        for node in islice(node_errors.values(), 20):
            if not isinstance(node, dict):
                continue
            errors = node.get("errors")
            if not isinstance(errors, list):
                continue
            for item in errors[:10]:
                if isinstance(item, dict):
                    parts.extend(value[:2000] for value in (item.get("type"), item.get("message"), item.get("details"))
                                 if isinstance(value, str))
    return "; ".join(parts)[:16000] or "Provider rejected workflow"


def _comfy_prompt_code(body: dict):
    error = body.get("error")
    return error.get("type") if isinstance(error, dict) else None


def _format_execution_status_error(status_obj: dict) -> str:
    """Extract bounded provider text without serializing the status payload."""
    msgs = status_obj.get("messages")
    if isinstance(msgs, list) and msgs:
        parts = []
        for item in msgs[-10:]:
            if isinstance(item, str):
                parts.append(item[:8000])
            elif isinstance(item, (list, tuple)) and len(item) == 2 and item[0] == "execution_error" and isinstance(item[1], dict):
                detail = item[1]
                for key in ("node_type", "exception_type", "exception_message"):
                    value = detail.get(key)
                    if isinstance(value, str):
                        parts.append(f"{key}: {value[:8000]}")
                frames = detail.get("traceback")
                if isinstance(frames, list):
                    parts.extend(frame[:2000] for frame in frames[-12:] if isinstance(frame, str))
        if parts:
            return "\n".join(parts)[-16000:]
    return "ComfyUI reported an execution failure"


def _execution_error_code(status_obj: dict):
    messages = status_obj.get("messages")
    if isinstance(messages, list):
        for item in reversed(messages[-10:]):
            if isinstance(item, (list, tuple)) and len(item) == 2 and item[0] == "execution_error" and isinstance(item[1], dict):
                return item[1].get("exception_type")
    return None


def validate_input(job_input):
    """
    Validates the input for the handler function.

    Args:
        job_input (dict): The input data to validate.

    Returns:
        tuple: A tuple containing the validated data and an error message, if any.
               The structure is (validated_data, error_message).
    """
    # Validate if job_input is provided
    if job_input is None:
        return None, "Please provide input"

    # Check if input is a string and try to parse it as JSON
    if isinstance(job_input, str):
        try:
            job_input = json.loads(job_input)
        except json.JSONDecodeError:
            return None, "Invalid JSON format in input"

    # Validate 'workflow' in input
    workflow = job_input.get("workflow")
    if workflow is None:
        return None, "Missing 'workflow' parameter"

    # Validate 'images' in input, if provided
    images = job_input.get("images")
    if images is not None:
        if not isinstance(images, list) or not all(
            "name" in image and "image" in image for image in images
        ):
            return (
                None,
                "'images' must be a list of objects with 'name' and 'image' keys",
            )

    # Return validated data and no error
    return {"workflow": workflow, "images": images}, None


def check_server(url, retries=500, delay=50, *, with_failure=False):
    """
    Check if a server is reachable via HTTP GET request

    Args:
    - url (str): The URL to check
    - retries (int, optional): The number of times to attempt connecting to the server. Default is 50
    - delay (int, optional): The time in milliseconds to wait between retries. Default is 500

    Returns:
    bool: True if the server is reachable within the given number of retries, otherwise False
    """

    last_error = None
    last_status = None
    for _ in range(retries):
        try:
            response = requests.get(url)

            # If the response status code is 200, the server is up and running
            if response.status_code == 200:
                print(f"runpod-worker-comfy - API is reachable")
                log_comfy_node_registry_once()
                return (True, None, None) if with_failure else True
            last_error = None
            last_status = response.status_code
        except requests.RequestException as e:
            last_error = e
            last_status = None

        # Wait for the specified delay before retrying
        time.sleep(delay / 1000)

    print(
        f"runpod-worker-comfy - Failed to connect to server at {url} after {retries} attempts."
    )
    return (False, last_error, last_status) if with_failure else False


def upload_images(images, job_id=None):
    """
    Upload a list of base64 encoded images to the ComfyUI server using the /upload/image endpoint.

    Args:
        images (list): A list of dictionaries, each containing the 'name' of the image and the 'image' as a base64 encoded string.
        server_address (str): The address of the ComfyUI server.

    Returns:
        list: A list of responses from the server for each image upload.
    """
    if not images:
        return {"status": "success", "message": "No images to upload", "details": []}

    responses = []
    upload_errors = []
    last_diagnostic = None

    print(f"runpod-worker-comfy - image(s) upload")

    for image in images:
        try:
            blob = base64.b64decode(image["image"])
            files = {
                "image": (image["name"], BytesIO(blob), "image/png"),
                "overwrite": (None, "true"),
            }
            response = requests.post(f"http://{COMFY_HOST}/upload/image", files=files)
            if response.status_code != 200:
                last_diagnostic = _log_comfy_failure("upload_image", "Image upload rejected", response.status_code, job_id)
                upload_errors.append("Image upload failed")
            else:
                responses.append("Image uploaded")
        except Exception as error:
            last_diagnostic = _log_handler_error("upload_image", error, job_id)
            upload_errors.append("Image upload failed")

    if upload_errors:
        print(f"runpod-worker-comfy - image(s) upload with errors")
        return {
            "status": "error",
            "message": "Some images failed to upload",
            "details": upload_errors,
            "diagnostic": last_diagnostic,
        }

    print(f"runpod-worker-comfy - image(s) upload complete")
    return {
        "status": "success",
        "message": "All images uploaded successfully",
        "details": responses,
    }


def queue_workflow(workflow, job_id=None):
    """
    Queue a workflow to be processed by ComfyUI.

    Returns:
        dict: Either ``{"prompt_id": "..."}`` on success or ``{"error": "..."}`` on validation/API failure.
    """
    data = json.dumps({"prompt": workflow}).encode("utf-8")
    req = urllib.request.Request(
        f"http://{COMFY_HOST}/prompt",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as response:
            raw = response.read()
    except urllib.error.HTTPError as e:
        raw = e.read() if e.fp else b"{}"
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            diagnostic = _log_comfy_failure("queue_workflow", "Non-JSON provider response: " +
                                            raw.decode("utf-8", errors="replace")[-16000:], e.code, job_id)
            return {"error": "ComfyUI rejected the workflow", "diagnostic": diagnostic}
        if isinstance(body, dict):
            diagnostic = _log_comfy_failure("queue_workflow", _format_comfy_prompt_error(body), e.code, job_id,
                                            _comfy_prompt_code(body))
        else:
            diagnostic = _log_comfy_failure("queue_workflow", "Unexpected provider response", e.code, job_id)
        return {"error": "ComfyUI rejected the workflow", "diagnostic": diagnostic}

    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        diagnostic = _log_comfy_failure("queue_workflow", "Non-JSON provider response: " +
                                        raw.decode("utf-8", errors="replace")[-16000:], job_id=job_id)
        return {"error": "ComfyUI returned an invalid response", "diagnostic": diagnostic}

    if not isinstance(body, dict):
        diagnostic = _log_comfy_failure("queue_workflow", "Unexpected provider response", job_id=job_id)
        return {"error": "ComfyUI returned an invalid response", "diagnostic": diagnostic}

    if body.get("error") is not None:
        diagnostic = _log_comfy_failure("queue_workflow", _format_comfy_prompt_error(body), job_id=job_id,
                                        code=_comfy_prompt_code(body))
        return {"error": "ComfyUI rejected the workflow", "diagnostic": diagnostic}

    prompt_id = body.get("prompt_id")
    if not prompt_id:
        diagnostic = _log_comfy_failure("queue_workflow", "Missing prompt ID", job_id=job_id)
        return {"error": "ComfyUI returned an invalid response", "diagnostic": diagnostic}

    return {"prompt_id": prompt_id}


def get_history(prompt_id):
    """
    Retrieve the history of a given prompt using its ID

    Args:
        prompt_id (str): The ID of the prompt whose history is to be retrieved

    Returns:
        dict: The history of the prompt, containing all the processing steps and results
    """
    with urllib.request.urlopen(f"http://{COMFY_HOST}/history/{prompt_id}") as response:
        return json.loads(response.read())


def base64_encode(img_path):
    """
    Returns base64 encoded image.

    Args:
        img_path (str): The path to the image

    Returns:
        str: The base64 encoded image
    """
    with open(img_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
        return f"{encoded_string}"


def process_output_images(outputs, job_id):
    """
    This function takes the "outputs" from image generation and the job ID,
    then determines the correct way to return the image, either as a direct URL
    to an AWS S3 bucket or as a base64 encoded string, depending on the
    environment configuration.

    Args:
        outputs (dict): A dictionary containing the outputs from image generation,
                        typically includes node IDs and their respective output data.
        job_id (str): The unique identifier for the job.

    Returns:
        dict: A dictionary with the status ('success' or 'error') and the message,
              which is either the URL to the image in the AWS S3 bucket or a base64
              encoded string of the image. In case of error, the message details the issue.

    The function works as follows:
    - It first determines the output path for the images from an environment variable,
      defaulting to "/comfyui/output" if not set.
    - It then iterates through the outputs to find the filenames of the generated images.
    - After confirming the existence of the image in the output folder, it checks if the
      AWS S3 bucket is configured via the BUCKET_ENDPOINT_URL environment variable.
    - If AWS S3 is configured, it uploads the image to the bucket and returns the URL.
    - If AWS S3 is not configured, it encodes the image in base64 and returns the string.
    - If the image file does not exist in the output folder, it returns an error status
      with a message indicating the missing image file.
    """

    COMFY_OUTPUT_PATH = os.environ.get("COMFY_OUTPUT_PATH", "/comfyui/output")

    output_images = []

    for node_id, node_output in outputs.items():
        if "images" in node_output:
            for image in node_output["images"]:
                output_images.append(os.path.join(image["subfolder"], image["filename"]))

    print(f"runpod-worker-comfy - image generation is done")

    if not output_images:
        print("runpod-worker-comfy - no output images found in workflow results")
        return {
            "status": "error",
            "message": "No output images found in workflow results",
        }

    result_images = []
    use_s3 = os.environ.get("BUCKET_ENDPOINT_URL", False)

    for rel_path in output_images:
        local_image_path = os.path.join(COMFY_OUTPUT_PATH, rel_path)
        print("runpod-worker-comfy - processing generated image")

        if not os.path.exists(local_image_path):
            print("runpod-worker-comfy - WARNING: generated image file is missing")
            continue

        if use_s3:
            image = rp_upload.upload_image(job_id, local_image_path)
            print("runpod-worker-comfy - image uploaded to AWS S3")
        else:
            image = base64_encode(local_image_path)
            print("runpod-worker-comfy - image converted to base64")

        result_images.append(image)

    if not result_images:
        return {
            "status": "error",
            "message": "None of the output images exist",
        }

    return {
        "status": "success",
        "message": result_images if len(result_images) > 1 else result_images[0],
    }


def handler(job):
    """
    The main function that handles a job of generating an image.

    This function validates the input, sends a prompt to ComfyUI for processing,
    polls ComfyUI for result, and retrieves generated images.

    Args:
        job (dict): A dictionary containing job details and input parameters.

    Returns:
        dict: A dictionary containing either an error message or a success status with generated images.
    """
    try:
        job_input = job["input"]
        validated_data, error_message = validate_input(job_input)
    except Exception as error:
        diagnostic = _log_handler_error("input_validation", error, job.get("id"))
        return {"error": "Invalid workflow input", "diagnostic": diagnostic}

    # Make sure that the input is valid
    if error_message:
        diagnostic = _log_comfy_failure("input_validation", job_id=job.get("id"))
        return {"error": error_message, "diagnostic": diagnostic}

    # Extract validated data
    workflow = validated_data["workflow"]
    images = validated_data.get("images")

    # Make sure that the ComfyUI API is available
    available, server_error, server_status = check_server(
        f"http://{COMFY_HOST}",
        COMFY_API_AVAILABLE_MAX_RETRIES,
        COMFY_API_AVAILABLE_INTERVAL_MS,
        with_failure=True,
    )
    if not available:
        diagnostic = (_log_handler_error("comfy_api", server_error, job.get("id")) if server_error else
                      _log_comfy_failure("comfy_api", "ComfyUI API is not reachable", server_status, job.get("id")))
        return {"error": "ComfyUI API is not reachable", "diagnostic": diagnostic}

    # Upload images if they exist
    upload_result = upload_images(images, job["id"])

    if upload_result["status"] == "error":
        return upload_result

    # Queue the workflow
    try:
        queued_workflow = queue_workflow(workflow, job["id"])
        if "error" in queued_workflow:
            err = queued_workflow["error"]
            return {"error": err, "diagnostic": queued_workflow.get("diagnostic")}
        prompt_id = queued_workflow["prompt_id"]
        print(f"runpod-worker-comfy - queued workflow with ID {prompt_id}")
    except Exception as e:
        diagnostic = _log_handler_error("queue_workflow", e, job["id"])
        return {"error": "Could not queue the workflow", "diagnostic": diagnostic}

    # Poll for completion
    print(f"runpod-worker-comfy - wait until image generation is complete")
    retries = 0
    try:
        while retries < COMFY_POLLING_MAX_RETRIES:
            history = get_history(prompt_id)

            if isinstance(history, dict) and prompt_id in history:
                entry = history[prompt_id]
                status_obj = entry.get("status")
                if isinstance(status_obj, dict) and status_obj.get("status_str") == "error":
                    detail = _format_execution_status_error(status_obj)
                    diagnostic = _log_comfy_failure("execute_workflow", detail, job_id=job["id"],
                                                    code=_execution_error_code(status_obj))
                    return {"error": "ComfyUI workflow failed", "diagnostic": diagnostic}
                if entry.get("outputs"):
                    break

            time.sleep(COMFY_POLLING_INTERVAL_MS / 1000)
            retries += 1
        else:
            diagnostic = _log_comfy_failure("poll_workflow", "Max retries reached", job_id=job["id"])
            return {"error": "Max retries reached while waiting for image generation", "diagnostic": diagnostic}
    except Exception as e:
        diagnostic = _log_handler_error("poll_workflow", e, job["id"])
        return {"error": "Could not check workflow progress", "diagnostic": diagnostic}

    # Get the generated image and return it as URL in an AWS bucket or as base64
    try:
        images_result = process_output_images(history[prompt_id].get("outputs"), job["id"])
    except Exception as error:
        diagnostic = _log_credential_failure("store_output_image", error, job["id"])
        return {"error": "Could not save generated images", "diagnostic": diagnostic}

    if images_result.get("status") == "error":
        diagnostic = _log_comfy_failure("process_output", images_result.get("message"), job_id=job["id"])
        images_result["diagnostic"] = diagnostic

    result = {**images_result, "refresh_worker": REFRESH_WORKER}

    return result


# Start the handler only if this script is run directly
if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
