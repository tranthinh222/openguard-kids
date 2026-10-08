import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Category = Literal["education", "entertainment", "social", "games", "age_inappropriate", "unknown"]
CATEGORIES = ["education", "entertainment", "social", "games", "age_inappropriate", "unknown"]


def normalize_domain(value: str) -> str:
    value = value.strip().rstrip(".").lower()
    if any(c in value for c in "/\\:@?#* "):
        raise ValueError("Use a domain only, without URL, path, port or wildcard")
    try:
        value = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("Invalid domain") from exc
    labels = value.split(".")
    if len(value) > 253 or len(labels) < 2 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
    ):
        raise ValueError("Invalid domain")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise ValueError("IP addresses are not domains")


def process_name(value: str) -> str:
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9_ .()+-]{1,120}\.exe", value):
        raise ValueError("Use executable filename only, e.g. game.exe")
    return value


class AppRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    sha256: str | None = None
    action: Literal["allow", "block"]

    _name = field_validator("name")(process_name)

    @field_validator("sha256")
    @classmethod
    def hash_value(cls, value):
        if not value:
            return None
        value = value.lower().strip()
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("SHA-256 must contain 64 hexadecimal characters")
        return value


class DomainPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allow: list[str] = Field(default_factory=list, max_length=1000)
    block: list[str] = Field(default_factory=list, max_length=1000)
    blocked_categories: list[Category] = Field(default_factory=lambda: ["social", "games", "age_inappropriate"], max_length=6)
    safe_search: bool = True

    @field_validator("allow", "block")
    @classmethod
    def domain_list(cls, values):
        normalized = [normalize_domain(value) for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("Duplicate domain rule")
        return normalized

    @model_validator(mode="after")
    def conflicts(self):
        if set(self.allow) & set(self.block):
            raise ValueError("A domain cannot be both allowed and blocked")
        if len(set(self.blocked_categories)) != len(self.blocked_categories):
            raise ValueError("Duplicate category")
        return self
