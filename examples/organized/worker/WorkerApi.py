import os
from typing import Any, Dict, List, Optional

import requests
from requests import Response, Session, RequestException

from dotenv import find_dotenv, load_dotenv
load_dotenv(find_dotenv(usecwd=True), override=False)


class WorkerApiClient:
    """
    Клиент для работы с API se-worker-controller.

    Базовый URL и UUID инстанса берутся из окружения, но могут быть переопределены через аргументы конструктора.

    Переменные окружения:
      SE_WORKER_BASE_URL - базовый адрес контроллера, например:
        (по умолчанию https://www.outenemy.ru/se/worker-controller)
      SE_WORKER_INSTANCE_UUID - UUID инстанса воркера
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        instance_uuid: Optional[str] = None,
        timeout: float = 15.0,
        session: Optional[Session] = None,
    ) -> None:
        env_base = os.getenv("SE_WORKER_BASE_URL", "https://www.outenemy.ru/se/worker-controller")
        env_uuid = os.getenv("SE_WORKER_INSTANCE_UUID")

        if base_url is None:
            base_url = env_base
        if instance_uuid is None:
            instance_uuid = env_uuid

        if not instance_uuid:
            raise ValueError(
                "Instance UUID is not set. "
                "Set SE_WORKER_INSTANCE_UUID or pass instance_uuid to WorkerApiClient."
            )

        self.base_url = self._normalize_base_url(base_url)
        self.instance_uuid = instance_uuid.strip()
        self.root_url = f"{self.base_url}/instance/{self.instance_uuid}"
        self.api_url = f"{self.root_url}/api"
        self.timeout = timeout
        self.session = session or requests.Session()

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        base_url = base_url.strip()
        if not base_url:
            raise ValueError("base_url is empty")
        if not base_url.startswith(("http://", "https://")):
            base_url = f"http://{base_url}"
        return base_url.rstrip("/")

    def _request(
        self,
        method: str,
        path: str,
        *,
        expected_status: int = -1,
        **kwargs: Any,
    ) -> Optional[Response]:
        """
        Внутренний helper для запросов.
        path передаётся относительно /api, например:
          "/programs"
          f"/programs/{uuid}/files"

        expected_status: -1 -> принимать любой 2xx как успех; n -> ожидать конкретный код n.
        """
        if not path.startswith("/"):
            path = "/" + path

        url = f"{self.api_url}{path}"

        try:
            response = self.session.request(
                method=method.upper(),
                url=url,
                timeout=self.timeout,
                **kwargs,
            )
        except RequestException as e:
            print(f"[WorkerApiClient] Request error {method} {url}: {e}")
            return None

        if expected_status == -1:
            if not 200 <= response.status_code < 300:
                print(
                    f"[WorkerApiClient] Unexpected status {response.status_code} "
                    f"for {method} {url}. Body: {response.text}"
                )
                return None
        else:
            if response.status_code != expected_status:
                print(
                    f"[WorkerApiClient] Unexpected status {response.status_code} "
                    f"(expected {expected_status}) for {method} {url}. "
                    f"Body: {response.text}"
                )
                return None

        return response

    # ----------------------------------------------------------
    # Методы API
    # ----------------------------------------------------------

    def get_running_programs(self) -> Optional[Dict[str, Any]]:
        """
        GET /api/programs/running
        """
        response = self._request("GET", "/programs/running")
        if response is None:
            return None

        try:
            return response.json()
        except ValueError as e:
            print(f"[get_running_programs] JSON parse error: {e}")
            print(f"Raw response: {response.text}")
            return None

    def get_programs(self) -> Optional[Dict[str, Any]]:
        """
        GET /api/programs
        """
        response = self._request("GET", "/programs")
        if response is None:
            return None

        try:
            return response.json()
        except ValueError as e:
            print(f"[get_running_programs] JSON parse error: {e}")
            print(f"Raw response: {response.text}")
            return None

    def create_program(self, name: str) -> Optional[Dict[str, Any]]:
        """
        POST /api/programs

        Body: { "name": "<program name>" }
        """
        payload = {"name": name}
        response = self._request("POST", "/programs", json=payload)
        if response is None:
            return None

        try:
            return response.json()
        except ValueError as e:
            print(f"[create_program] JSON parse error: {e}")
            print(f"Raw response: {response.text}")
            return None

    def upload_files(self, program_uuid: str, file_paths: List[str]) -> bool:
        """
        POST /api/programs/{program_uuid}/files

        multipart/form-data, поле "files"
        """
        if not file_paths:
            print("[upload_files] file_paths is empty")
            return False

        files = []
        try:
            for path in file_paths:
                file_obj = open(path, "rb")
                files.append(("files", (os.path.basename(path), file_obj)))
        except OSError as e:
            print(f"[upload_files] File open error: {e}")
            for _, (_, f) in files:
                f.close()
            return False

        path = f"/programs/{program_uuid}/files"
        try:
            response = self._request(
                "POST",
                path,
                files=files,
            )
        finally:
            for _, (_, f) in files:
                f.close()

        return response is not None

    def list_program_files(self, program_uuid: str) -> Optional[Any]:
        """
        GET /api/programs/{program_uuid}/files

        Формат зависит от backend-а:
          - список файлов;
          - или { "items": [...] }.
        """
        path = f"/programs/{program_uuid}/files"
        response = self._request("GET", path)
        if response is None:
            return None

        try:
            data = response.json()
        except ValueError as e:
            print(f"[list_program_files] JSON parse error: {e}")
            print(f"Raw response: {response.text}")
            return None

        if isinstance(data, dict) and "items" in data:
            return data["items"]
        return data

    def run_program(
        self,
        program_uuid: str,
        filename: str,
        grid_id: str,
        params: Optional[dict] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        POST /api/programs/{program_uuid}/run

        Body: { "filename": "...", "grid_id": "...", "params": "..." }
        """
        payload = {"filename": filename, "grid_id": grid_id}
        if params is not None:
            payload["params"] = params
            
        path = f"/programs/{program_uuid}/run"
        response = self._request("POST", path, json=payload)
        if response is None:
            return None

        try:
            return response.json()
        except ValueError as e:
            print(f"[run_program] JSON parse error: {e}")
            print(f"Raw response: {response.text}")
            return None

    def get_program_logs(
        self,
        program_uuid: str,
        tail_bytes: Optional[int] = None,
    ) -> Optional[str]:
        """
        GET /api/programs/{program_uuid}/logs
        """
        params = {}
        if tail_bytes is not None:
            params["tail_bytes"] = str(tail_bytes)

        path = f"/programs/{program_uuid}/logs"
        response = self._request("GET", path, params=params)
        if response is None:
            return None

        return response.text

    def stop_program(self, program_uuid: str) -> bool:
        """
        POST /api/programs/{program_uuid}/stop
        """
        path = f"/programs/{program_uuid}/stop"
        response = self._request("POST", path)
        return response is not None

    def delete_program(self, program_uuid: str) -> bool:
        """
        DELETE /api/programs/{program_uuid}
        """
        path = f"/programs/{program_uuid}"
        response = self._request("DELETE", path)
        return response is not None


def example_usage() -> None:
    """
    Пример использования клиента.

    Перед запуском выстави переменные окружения:
      SE_WORKER_BASE_URL="https://www.outenemy.ru/se/worker-controller"
      SE_WORKER_INSTANCE_UUID="28f8784e-dbe4-5f5e-b294-c1c87df4b712"
    """
    client = WorkerApiClient()

    program = client.create_program("Example from WorkerApiClient")
    if not program:
        print("Program creation failed")
        return

    program_uuid = program.get("uuid") or program.get("id")
    print(f"Created program: {program_uuid}")

    script_path = "main.py"
    if os.path.exists(script_path):
        uploaded = client.upload_files(program_uuid, [script_path])
        print(f"File upload: {uploaded}")
    else:
        print(f"File {script_path} does not exist, skip upload")

    files = client.list_program_files(program_uuid)
    print(f"Files: {files}")

    logs = client.get_program_logs(program_uuid, tail_bytes=2000)
    if logs is not None:
        print("=== Logs ===")
        print(logs)
