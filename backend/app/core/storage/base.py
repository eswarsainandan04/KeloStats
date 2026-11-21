from abc import ABC, abstractmethod
from typing import BinaryIO, List, Optional, Union


class BaseStorageAdapter(ABC):
    """
    Abstract Base Class for storage adapters.
    Provides a standardized contract for both local filesystem storage
    and cloud object storage (S3 / Supabase).
    """

    @abstractmethod
    def create(
        self,
        key: str,
        data: Union[bytes, str, BinaryIO],
        content_type: Optional[str] = None,
    ) -> str:
        """
        Creates/uploads a new file at the specified key.

        :param key: Relative destination path/key (e.g., 'workspace/uid/pid/slides/slide_1.svg').
        :param data: File content as bytes, text string, or binary stream.
        :param content_type: Optional MIME type (e.g., 'image/svg+xml', 'application/pdf').
        :return: Clean key or relative path of the created file.
        """
        pass

    @abstractmethod
    def read(self, key: str) -> bytes:
        """
        Reads and returns the raw binary content of the file.

        :param key: Relative path/key of the file.
        :return: File content as bytes.
        :raises FileNotFoundError: If the file does not exist.
        """
        pass

    def read_bytes(self, key: str) -> bytes:
        """
        Alias for read() returning raw binary content of the file.

        :param key: Relative path/key of the file.
        :return: File content as bytes.
        :raises FileNotFoundError: If the file does not exist.
        """
        return self.read(key)

    def read_text(self, key: str, encoding: str = "utf-8") -> str:
        """
        Reads and returns the text content of the file.

        :param key: Relative path/key of the file.
        :param encoding: Text encoding (default: 'utf-8').
        :return: Decoded string content.
        :raises FileNotFoundError: If the file does not exist.
        """
        return self.read(key).decode(encoding)

    @abstractmethod
    def update(
        self,
        key: str,
        data: Union[bytes, str, BinaryIO],
        content_type: Optional[str] = None,
    ) -> str:
        """
        Updates/overwrites an existing file at the specified key.

        :param key: Relative destination path/key.
        :param data: New file content as bytes, text string, or binary stream.
        :param content_type: Optional MIME type.
        :return: Clean key or relative path of the updated file.
        """
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """
        Deletes a single file at the specified key.

        :param key: Relative path/key of the file.
        :return: True if successfully deleted or already absent, False on error.
        """
        pass

    @abstractmethod
    def delete_prefix(self, prefix: str) -> int:
        """
        Deletes all files under the specified prefix/folder (e.g., a project workspace).

        :param prefix: Folder prefix (e.g., 'workspace/uid/pid/').
        :return: Number of deleted items.
        """
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """
        Checks whether a file exists at the specified key.

        :param key: Relative path/key of the file.
        :return: True if the file exists, False otherwise.
        """
        pass

    @abstractmethod
    def list_files(self, prefix: str = "") -> List[str]:
        """
        Lists all file keys under a given prefix.

        :param prefix: Folder prefix to search under (e.g., 'documents/uid/').
        :return: List of matching keys.
        """
        pass

    @abstractmethod
    def get_url(self, key: str, expires_in: int = 3600) -> str:
        """
        Returns a reachable URL or local file path for accessing the file.

        :param key: Relative path/key of the file.
        :param expires_in: Expiration time in seconds for presigned links.
        :return: URL or local path string.
        """
        pass
