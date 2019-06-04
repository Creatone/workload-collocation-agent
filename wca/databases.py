# Copyright (c) 2019 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import logging
import os
import string
import requests
import json
import base64

from abc import ABC
from typing import Optional, List, Union

from dataclasses import dataclass

from wca.config import assure_type, Numeric, Path
from wca.security import SSLCert

log = logging.getLogger(__name__)


class InvalidKey(Exception):
    pass


class TimeoutOnAllHosts(Exception):
    pass


class Database(ABC):

    def set(self, key: bytes, value: bytes):
        """Store data at key.
        Set is guarantee value to store data as a whole.
        """
        ...

    def get(self, key: bytes) -> Optional[bytes]:
        """Retrieve data from key.
        Returns None if key does not exits.
        """
        ...


_VALID_FILENAME_CHARACTERS = bytes("-_.%s%s" % (string.ascii_letters, string.digits), 'ascii')


def _validate_key(key: bytes):
    assure_type(key, bytes)

    if not (0 < len(key) <= 255):
        raise InvalidKey('Max key length is 255 bytes')

    for character in key:
        if character not in _VALID_FILENAME_CHARACTERS:
            raise InvalidKey()


def _validate_value(value: bytes):
    assure_type(value, bytes)


@dataclass
class LocalDatabase(Database):
    """Stores files under directory"""

    directory: str

    def __post_init__(self):
        os.makedirs(self.directory)

    def set(self, key: bytes, value: bytes):
        _validate_key(key)
        _validate_value(value)

        formatted_key = key.decode('ascii')

        full_path = os.path.join(self.directory, formatted_key)

        with open(full_path, 'wb') as f:
            f.write(value)

    def get(self, key: bytes) -> bytes:
        _validate_key(key)

        formatted_key = key.decode('ascii')

        full_path = os.path.join(self.directory, formatted_key)

        if not os.path.exists(full_path):
            return None

        with open(full_path, 'rb') as f:
            return f.read()


@dataclass
class ZookeeperDatabase(Database):
    # used as prefix for key, to namespace all queries
    hosts: List[str]
    namespace: str
    timeout: Numeric(1, 60) = 5.  # request timeout in seconds (tries another host) [s]
    ssl_verify: Union[bool, Path] = True
    ssl_client: Optional[SSLCert] = None

    def __post_init__(self):
        from kazoo.client import KazooClient

        self._client = KazooClient(
                hosts=self.hosts,
                timeout=self.timeout,
                )

        if self.ssl_client:
            self._client.certfile = self.ssl_client.cert_path
            self._client.keyfile = self.ssl_client.key_path

        if isinstance(self.ssl_verify, Path):
            self._client.use_ssl = True
            self._client.ca = self.ssl_verify
        else:
            self._client.use_ssl = self.ssl_verify

        self._client.start()

    def set(self, key: bytes, value: bytes):
        _validate_key(key)
        _validate_value(value)

        formatted_key = key.decode('ascii')

        full_path = os.path.join(self.namespace, formatted_key)

        self._client.ensure_path(full_path)

        self._client.set(full_path, value)

    def get(self, key: bytes) -> bytes:
        from kazoo.exceptions import NoNodeError
        _validate_key(key)

        formatted_key = key.decode('ascii')

        full_path = os.path.join(self.namespace, formatted_key)

        try:
            data = self._client.get(full_path)
            return bytes(data[0])
        except NoNodeError:
            return None


@dataclass
class EtcdDatabase(Database):
    """Access etcd using internal grpc-gateway.

    Support version: 3.2.x (version) (other versions require change of api_path)

    https://coreos.com/etcd/docs/latest/dev-guide/api_grpc_gateway.html
    """

    hosts: List[str]
    timeout: Optional[Numeric(1, 60)] = 5.0
    api_path: Optional[str] = '/v3alpha'
    ssl_client: Optional[SSLCert] = None

    def _send(self, url, data):
        response_data = None
        verify = False
        cert = None

        if self.ssl_client:
            verify = True
            cert = self.ssl_client.get_certs()

        for host in self.hosts:
            try:
                r = requests.post(
                        '{}{}{}'.format(host, self.api_path, url),
                        data=json.dumps(data), timeout=self.timeout,
                        verify=verify,
                        cert=cert)
                r.raise_for_status()
                response_data = r.json()
                break
            except requests.exceptions.Timeout:
                log.warning(
                        'EtcdDatabase: Timeout on host {}'.format(host))

        return response_data

    def _format_data(self, data):
        formatted_data = dict()

        for key in data.keys():
            formatted_data[key] = base64.b64encode(data[key]).decode('ascii')

        return formatted_data

    def set(self, key: bytes, value: bytes):
        _validate_key(key)
        _validate_value(value)

        data = {'key': key, 'value': value}

        formatted_data = self._format_data(data)

        url = '/kv/put'

        response_data = self._send(url, formatted_data)

        if not response_data:
            raise TimeoutOnAllHosts(
                    'EtcdDatabase: Cannot put key "{}": Timeout on all hosts!'.format(key))

    def get(self, key) -> bytes:
        _validate_key(key)

        data = {'key': key}

        formatted_data = self._format_data(data)

        url = '/kv/range'

        response_data = self._send(url, formatted_data)

        if not response_data:
            raise TimeoutOnAllHosts(
                    'EtcdDatabase: Cannot get key "{}": Timeout on all hosts!'.format(key))

        if 'kvs' in response_data:
            if 'value' in response_data['kvs'][0]:
                return base64.b64decode(response_data['kvs'][0]['value'])

        return None
