"""
Sistema de Autenticação — MCS B3
Usuarios definidos em usuarios.json (sem banco de dados).
Roles: 'sup' (superusuário, pode gerenciar usuários) e 'user' (acesso normal).
"""

import os
import json
import uuid
import hashlib
import hmac
from typing import Optional, List, Dict
from flask_login import UserMixin

USUARIOS_FILE = os.path.join(os.path.dirname(__file__), 'usuarios.json')

# ── Hash de senha (SHA-256 + salt, sem dependência externa) ────────────────────
def _hash_senha(senha: str, salt: str = '') -> str:
    """Gera hash seguro da senha com salt."""
    if not salt:
        salt = uuid.uuid4().hex
    h = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), salt.encode('utf-8'), 260000)
    return f"{salt}${h.hex()}"

def _verificar_senha(senha: str, hash_armazenado: str) -> bool:
    """Verifica se a senha bate com o hash armazenado."""
    if not hash_armazenado or '$' not in hash_armazenado:
        return False
    salt, _ = hash_armazenado.split('$', 1)
    hash_novo = _hash_senha(senha, salt)
    return hmac.compare_digest(hash_novo, hash_armazenado)


# ── Modelo de usuário ──────────────────────────────────────────────────────────
class Usuario(UserMixin):
    def __init__(self, dados: Dict):
        self.id            = dados['id']
        self.username      = dados['username']
        self.nome          = dados.get('nome', dados['username'])
        self.password_hash = dados.get('password_hash', '')
        self.role          = dados.get('role', 'user')
        self.ativo         = dados.get('ativo', True)

    @property
    def is_sup(self) -> bool:
        return self.role == 'sup'

    def verificar_senha(self, senha: str) -> bool:
        return _verificar_senha(senha, self.password_hash)

    def to_dict(self) -> Dict:
        return {
            'id':            self.id,
            'username':      self.username,
            'nome':          self.nome,
            'password_hash': self.password_hash,
            'role':          self.role,
            'ativo':         self.ativo,
        }


# ── Persistência ───────────────────────────────────────────────────────────────
def _carregar_usuarios() -> List[Dict]:
    try:
        with open(USUARIOS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('usuarios', [])
    except FileNotFoundError:
        return []
    except Exception:
        return []


def _salvar_usuarios(usuarios: List[Dict]) -> None:
    try:
        dados = {}
        if os.path.exists(USUARIOS_FILE):
            with open(USUARIOS_FILE, 'r', encoding='utf-8') as f:
                dados = json.load(f)
        dados['usuarios'] = usuarios
        with open(USUARIOS_FILE, 'w', encoding='utf-8') as f:
            json.dump(dados, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise RuntimeError(f'Erro ao salvar usuarios.json: {e}')


# ── API pública ────────────────────────────────────────────────────────────────
def buscar_por_id(user_id: str) -> Optional[Usuario]:
    for u in _carregar_usuarios():
        if u['id'] == user_id:
            return Usuario(u)
    return None


def buscar_por_username(username: str) -> Optional[Usuario]:
    for u in _carregar_usuarios():
        if u['username'].lower() == username.lower():
            return Usuario(u)
    return None


def listar_usuarios() -> List[Usuario]:
    return [Usuario(u) for u in _carregar_usuarios()]


def criar_usuario(username: str, nome: str, senha: str, role: str = 'user') -> Usuario:
    """Cria um novo usuário. Lança ValueError se username já existe."""
    if buscar_por_username(username):
        raise ValueError(f"Usuário '{username}' já existe.")
    if len(senha) < 4:
        raise ValueError("A senha deve ter pelo menos 4 caracteres.")

    usuarios = _carregar_usuarios()
    novo_id  = str(max((int(u['id']) for u in usuarios), default=0) + 1)
    novo = {
        'id':            novo_id,
        'username':      username.strip().lower(),
        'nome':          nome.strip(),
        'password_hash': _hash_senha(senha),
        'role':          role if role in ('sup', 'user') else 'user',
        'ativo':         True,
    }
    usuarios.append(novo)
    _salvar_usuarios(usuarios)
    return Usuario(novo)


def alterar_senha(user_id: str, nova_senha: str) -> None:
    """Altera a senha de um usuário."""
    if len(nova_senha) < 4:
        raise ValueError("A senha deve ter pelo menos 4 caracteres.")
    usuarios = _carregar_usuarios()
    for u in usuarios:
        if u['id'] == user_id:
            u['password_hash'] = _hash_senha(nova_senha)
            _salvar_usuarios(usuarios)
            return
    raise ValueError("Usuário não encontrado.")


def remover_usuario(user_id: str) -> None:
    """Remove um usuário. Não permite remover o último SUP."""
    usuarios = _carregar_usuarios()
    alvo = next((u for u in usuarios if u['id'] == user_id), None)
    if not alvo:
        raise ValueError("Usuário não encontrado.")
    # Garante que sempre existe pelo menos 1 SUP ativo
    sups_ativos = [u for u in usuarios if u['role'] == 'sup' and u['ativo'] and u['id'] != user_id]
    if alvo['role'] == 'sup' and not sups_ativos:
        raise ValueError("Não é possível remover o último superusuário.")
    usuarios = [u for u in usuarios if u['id'] != user_id]
    _salvar_usuarios(usuarios)


def toggle_ativo(user_id: str) -> bool:
    """Ativa/desativa um usuário. Retorna o novo estado."""
    usuarios = _carregar_usuarios()
    for u in usuarios:
        if u['id'] == user_id:
            u['ativo'] = not u.get('ativo', True)
            _salvar_usuarios(usuarios)
            return u['ativo']
    raise ValueError("Usuário não encontrado.")


def inicializar_admin_se_necessario() -> None:
    """
    Se não existe nenhum usuário SUP com senha, cria o admin padrão.
    Chamado na inicialização do app.
    """
    usuarios = _carregar_usuarios()
    sups_com_senha = [
        u for u in usuarios
        if u.get('role') == 'sup' and u.get('password_hash') and '$' in u.get('password_hash', '')
    ]
    if not sups_com_senha:
        # Primeiro acesso — admin com senha padrão "admin123"
        # O usuário é forçado a trocar na primeira sessão
        try:
            admins = [u for u in usuarios if u.get('username') == 'admin']
            if admins:
                admins[0]['password_hash'] = _hash_senha('admin123')
                admins[0]['force_password_change'] = True
                _salvar_usuarios(usuarios)
            else:
                criar_usuario('admin', 'Administrador', 'admin123', role='sup')
        except Exception:
            pass
