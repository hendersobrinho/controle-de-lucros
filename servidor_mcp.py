"""Abre o servidor MCP do Controle de Lucros (ver controle_lucros/mcp_servidor.py).

Existe para o Claude Desktop e o Claude Code chamarem pelo caminho do
arquivo: o Python põe a pasta do script no caminho de importação, então o
pacote controle_lucros é achado de qualquer pasta — o Claude Desktop não
deixa escolher a pasta de trabalho do servidor.
"""
from controle_lucros.mcp_servidor import main

if __name__ == "__main__":
    main()
