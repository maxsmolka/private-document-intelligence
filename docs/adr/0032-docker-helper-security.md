# ADR 0032: Docker socket and helper security

Status: Accepted

The API and web services receive no Docker socket. Docker control is root-equivalent and remains in an operator-invoked host process. Commands use fixed argument vectors, official repositories, project `pdi`, known services, and resolved operator-configured files. A remotely reachable privileged helper is deferred unless a narrow authenticated local-socket protocol is proven necessary.
