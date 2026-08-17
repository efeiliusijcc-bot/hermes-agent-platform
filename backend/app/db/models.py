from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, Table, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


agent_skill = Table(
    "agent_skill",
    Base.metadata,
    Column("agent_id", String(64), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("skill_id", String(64), ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True),
    Column("version", String(64), nullable=False, server_default="latest"),
)

agent_mcp = Table(
    "agent_mcp",
    Base.metadata,
    Column("agent_id", String(64), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("mcp_id", String(64), ForeignKey("mcp_servers.id", ondelete="CASCADE"), primary_key=True),
    Column("permission", String(32), nullable=False, server_default="read_only"),
    CheckConstraint("permission = 'read_only'", name="ck_agent_mcp_permission"),
)

agent_knowledge = Table(
    "agent_knowledge",
    Base.metadata,
    Column("agent_id", String(64), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("source_id", String(64), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), primary_key=True),
)

execution_artifact = Table(
    "execution_artifacts",
    Base.metadata,
    Column(
        "execution_id",
        UUID(as_uuid=True),
        ForeignKey("execution_logs.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "artifact_id",
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive', 'archived')",
            name="ck_agents_status",
        ),
        CheckConstraint("response_mode IN ('sync', 'stream')", name="ck_agents_response_mode"),
        CheckConstraint(
            "model_adapter IN ('hermes', 'qwen', 'deepseek', 'gpt', 'claude')",
            name="ck_agents_model_adapter",
        ),
        CheckConstraint("agent_type IN ('manager', 'worker')", name="ck_agents_agent_type"),
        CheckConstraint(
            "runtime_type IN ('hermes', 'pi', 'deepseek')", name="ck_agents_runtime_type"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    agent_type: Mapped[str] = mapped_column(String(32), nullable=False, default="worker")
    parent_agent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    model_settings: Mapped[dict[str, Any]] = mapped_column("model_config", JSONB, nullable=False, default=dict)
    model: Mapped[str] = mapped_column(String(255), nullable=False, default="hermes-agent")
    prompt_template: Mapped[str] = mapped_column(Text, nullable=False, default="{{input}}")
    model_adapter: Mapped[str] = mapped_column(String(32), nullable=False, default="hermes")
    runtime_type: Mapped[str] = mapped_column(String(32), nullable=False, default="hermes")
    runtime_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runtimes.id", ondelete="SET NULL"), nullable=True
    )
    runtime_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    capability_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    api_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    response_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="sync")
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    skills: Mapped[list[Skill]] = relationship(secondary=agent_skill, lazy="selectin")
    mcp_servers: Mapped[list[MCPServer]] = relationship(secondary=agent_mcp, lazy="selectin")
    knowledge_sources: Mapped[list[KnowledgeSource]] = relationship(secondary=agent_knowledge, lazy="selectin")
    execution_logs: Mapped[list[ExecutionLog]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    sessions: Mapped[list[AgentSession]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    tasks: Mapped[list[AgentTask]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    schema_versions: Mapped[list[AgentSchemaVersion]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    api_versions: Mapped[list[AgentAPIVersion]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    publication: Mapped[AgentPublication | None] = relationship(
        back_populates="agent", cascade="all, delete-orphan", uselist=False
    )
    api_client_bindings: Mapped[list[AgentAPIClient]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    audit_logs: Mapped[list[AuditLog]] = relationship(back_populates="agent")
    metrics: Mapped[list[AgentMetric]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    versions: Mapped[list[AgentVersion]] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
        foreign_keys="AgentVersion.agent_id",
    )
    current_version: Mapped[AgentVersion | None] = relationship(
        foreign_keys=[current_version_id], post_update=True
    )
    parent_agent: Mapped[Agent | None] = relationship(
        back_populates="child_agents", remote_side=[id], foreign_keys=[parent_agent_id]
    )
    child_agents: Mapped[list[Agent]] = relationship(
        back_populates="parent_agent", foreign_keys=[parent_agent_id]
    )
    owned_teams: Mapped[list[AgentTeam]] = relationship(
        back_populates="owner_agent", foreign_keys="AgentTeam.owner_agent_id"
    )
    team_memberships: Mapped[list[TeamMember]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )


class AgentTeam(Base):
    __tablename__ = "agent_teams"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive', 'archived')", name="ck_agent_teams_status"),
        UniqueConstraint("name", name="uq_agent_teams_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    owner_agent: Mapped[Agent] = relationship(back_populates="owned_teams", foreign_keys=[owner_agent_id])
    members: Mapped[list[TeamMember]] = relationship(
        back_populates="team", cascade="all, delete-orphan", lazy="selectin"
    )
    workflows: Mapped[list[Workflow]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )
    runs: Mapped[list[WorkflowRun]] = relationship(back_populates="team")


class TeamMember(Base):
    __tablename__ = "team_members"
    __table_args__ = (
        CheckConstraint("priority BETWEEN 0 AND 100", name="ck_team_members_priority"),
    )

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_teams.id", ondelete="CASCADE"), primary_key=True
    )
    agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(128), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    team: Mapped[AgentTeam] = relationship(back_populates="members")
    agent: Mapped[Agent] = relationship(back_populates="team_memberships", lazy="joined")


class Workflow(Base):
    __tablename__ = "workflows"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'inactive', 'archived')", name="ck_workflows_status"),
        UniqueConstraint("team_id", "name", name="uq_workflows_team_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_teams.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    team: Mapped[AgentTeam] = relationship(back_populates="workflows")
    # Completed Run history outlives an editable Workflow definition.  The
    # database FK uses ON DELETE SET NULL, so ORM deletes must preserve the
    # same audit-history contract instead of cascading into workflow_runs.
    runs: Mapped[list[WorkflowRun]] = relationship(
        back_populates="workflow", passive_deletes=True
    )


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'human_review', 'succeeded', 'failed', 'cancelled')",
            name="ck_workflow_runs_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="SET NULL")
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_teams.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    input: Mapped[str] = mapped_column(Text, nullable=False)
    output: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workflow: Mapped[Workflow | None] = relationship(back_populates="runs")
    team: Mapped[AgentTeam] = relationship(back_populates="runs")
    tasks: Mapped[list[AgentTask]] = relationship(back_populates="workflow_run")


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="0.0.0")
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    runtime_support: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=lambda: ["hermes"]
    )
    package_sha256: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class MCPServer(Base):
    __tablename__ = "mcp_servers"
    __table_args__ = (
        CheckConstraint("permission = 'read_only'", name="ck_mcp_servers_permission"),
        CheckConstraint("status IN ('unknown', 'online', 'offline')", name="ck_mcp_servers_status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    permission: Mapped[str] = mapped_column(String(32), nullable=False, default="read_only")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AgentRuntime(Base):
    __tablename__ = "agent_runtimes"
    __table_args__ = (
        CheckConstraint("type IN ('hermes', 'pi', 'deepseek')", name="ck_agent_runtimes_type"),
        CheckConstraint(
            "status IN ('unknown', 'online', 'offline', 'disabled')",
            name="ck_agent_runtimes_status",
        ),
        UniqueConstraint("name", name="uq_agent_runtimes_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AgentPublication(Base):
    __tablename__ = "agent_publications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'testing', 'published', 'disabled')",
            name="ck_agent_publications_status",
        ),
    )

    agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    api_key_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    api_key_prefix: Mapped[str | None] = mapped_column(String(16))
    call_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    last_called_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    agent: Mapped[Agent] = relationship(back_populates="publication", lazy="joined")


class AgentSchemaVersion(Base):
    __tablename__ = "agent_schema_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_schema_versions_agent_version"),
        CheckConstraint(
            "status IN ('draft', 'testing', 'published', 'deprecated', 'disabled')",
            name="ck_agent_schema_versions_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent: Mapped[Agent] = relationship(back_populates="schema_versions")
    api_versions: Mapped[list[AgentAPIVersion]] = relationship(back_populates="schema_version")


class AgentAPIVersion(Base):
    __tablename__ = "agent_api_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "api_version", name="uq_agent_api_versions_agent_version"),
        CheckConstraint(
            "status IN ('draft', 'testing', 'published', 'deprecated', 'disabled')",
            name="ck_agent_api_versions_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    api_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_schema_versions.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent: Mapped[Agent] = relationship(back_populates="api_versions")
    schema_version: Mapped[AgentSchemaVersion] = relationship(back_populates="api_versions", lazy="joined")


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="ck_knowledge_sources_status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    documents: Mapped[list[KnowledgeDocument]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("source_id", "sha256", name="uq_knowledge_documents_source_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("knowledge_sources.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    parser: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    source: Mapped[KnowledgeSource] = relationship(back_populates="documents")


class ExecutionLog(Base):
    __tablename__ = "execution_logs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_execution_logs_status",
        ),
        CheckConstraint(
            "response_mode IN ('sync', 'stream', 'async')",
            name="ck_execution_logs_response_mode",
        ),
        CheckConstraint(
            "priority IS NULL OR priority BETWEEN 0 AND 9",
            name="ck_execution_logs_priority",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_execution_logs_duration",
        ),
        CheckConstraint(
            "token_usage IS NULL OR token_usage >= 0",
            name="ck_execution_logs_token_usage",
        ),
        CheckConstraint(
            "runtime_type IN ('hermes', 'pi', 'deepseek')", name="ck_execution_logs_runtime_type"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input: Mapped[str] = mapped_column(Text, nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output: Mapped[str | None] = mapped_column(Text)
    output_json: Mapped[Any | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    response_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="sync")
    priority: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    token_usage: Mapped[int | None] = mapped_column(BigInteger)
    runtime_type: Mapped[str] = mapped_column(String(32), nullable=False, default="hermes")
    runtime_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runtimes.id", ondelete="SET NULL"), nullable=True
    )
    runtime_version: Mapped[str | None] = mapped_column(String(64))
    retry_of_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_logs.id", ondelete="SET NULL"), nullable=True
    )
    agent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent: Mapped[Agent] = relationship(back_populates="execution_logs")
    session: Mapped[AgentSession | None] = relationship(back_populates="execution_logs")
    steps: Mapped[list[ExecutionStep]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", order_by="ExecutionStep.sequence"
    )
    artifacts: Mapped[list[Artifact]] = relationship(secondary=execution_artifact, lazy="selectin")
    retry_of: Mapped[ExecutionLog | None] = relationship(
        remote_side="ExecutionLog.id", foreign_keys=[retry_of_execution_id]
    )
    agent_version: Mapped[AgentVersion | None] = relationship(
        foreign_keys=[agent_version_id], lazy="joined"
    )


class ExecutionStep(Base):
    __tablename__ = "execution_steps"
    __table_args__ = (
        UniqueConstraint("execution_id", "step_key", name="uq_execution_steps_execution_key"),
        CheckConstraint(
            "step_type IN ('request', 'schema', 'memory', 'skill', 'mcp', 'knowledge', "
            "'model', 'artifact', 'runtime', 'plan', 'repository', 'code', 'test', 'git')",
            name="ck_execution_steps_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed', 'skipped', 'cancelled')",
            name="ck_execution_steps_status",
        ),
        CheckConstraint("sequence >= 0", name="ck_execution_steps_sequence"),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="ck_execution_steps_latency"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_logs.id", ondelete="CASCADE"), nullable=False
    )
    step_key: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(String(32), nullable=False)
    step_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    input_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(BigInteger)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    execution: Mapped[ExecutionLog] = relationship(back_populates="steps")


class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')",
            name="ck_agent_sessions_status",
        ),
        CheckConstraint(
            "runtime_type IN ('hermes', 'pi', 'deepseek')", name="ck_agent_sessions_runtime_type"
        ),
        CheckConstraint(
            "workspace_type IN ('document', 'repository')",
            name="ck_agent_sessions_workspace_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(128))
    memory_session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    runtime_type: Mapped[str] = mapped_column(String(32), nullable=False, default="hermes")
    runtime_session_id: Mapped[str | None] = mapped_column(String(255))
    workspace_type: Mapped[str] = mapped_column(String(32), nullable=False, default="document")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    input: Mapped[str] = mapped_column(Text, nullable=False)
    output: Mapped[str | None] = mapped_column(Text)
    workspace_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent: Mapped[Agent] = relationship(back_populates="sessions")
    execution_logs: Mapped[list[ExecutionLog]] = relationship(back_populates="session")
    task: Mapped[AgentTask | None] = relationship(back_populates="session", uselist=False)
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="session", cascade="all, delete-orphan")


class AgentTask(Base):
    __tablename__ = "agent_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'waiting_child', 'human_review', 'retrying', 'succeeded', 'failed', 'cancelled')",
            name="ck_agent_tasks_status",
        ),
        CheckConstraint("priority BETWEEN 0 AND 9", name="ck_agent_tasks_priority"),
        CheckConstraint("attempt >= 0 AND max_attempts >= 1", name="ck_agent_tasks_attempts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_tasks.id", ondelete="CASCADE")
    )
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="SET NULL")
    )
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE")
    )
    node_key: Mapped[str | None] = mapped_column(String(128))
    node_type: Mapped[str] = mapped_column(String(32), nullable=False, default="agent")
    depends_on: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    input_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("execution_logs.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    worker_id: Mapped[str | None] = mapped_column(String(128))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent: Mapped[Agent] = relationship(back_populates="tasks")
    session: Mapped[AgentSession] = relationship(back_populates="task", lazy="joined")
    parent_task: Mapped[AgentTask | None] = relationship(
        back_populates="child_tasks", remote_side=[id], foreign_keys=[parent_task_id]
    )
    child_tasks: Mapped[list[AgentTask]] = relationship(
        back_populates="parent_task", foreign_keys=[parent_task_id], cascade="all, delete-orphan"
    )
    workflow_run: Mapped[WorkflowRun | None] = relationship(back_populates="tasks")


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("session_id", "filename", name="uq_artifacts_session_filename"),
        UniqueConstraint("storage_type", "storage_path", name="uq_artifacts_storage_location"),
        CheckConstraint("size_bytes >= 0", name="ck_artifacts_size"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_type: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False, default="text")
    runtime_source: Mapped[str] = mapped_column(String(32), nullable=False, default="platform")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    agent: Mapped[Agent] = relationship(back_populates="artifacts")
    session: Mapped[AgentSession] = relationship(back_populates="artifacts")


class AgentMemory(Base):
    __tablename__ = "agent_memories"
    __table_args__ = (
        UniqueConstraint(
            "agent_id", "session_id", "memory_type", "key",
            name="uq_agent_memories_namespace_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class APIClient(Base):
    __tablename__ = "api_clients"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'suspended', 'revoked')",
            name="ck_api_clients_status",
        ),
        CheckConstraint("rate_limit_per_minute > 0", name="ck_api_clients_rate_limit"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    agent_bindings: Mapped[list[AgentAPIClient]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list[APIKey]] = relationship(back_populates="client", cascade="all, delete-orphan")
    audit_logs: Mapped[list[AuditLog]] = relationship(back_populates="client")


class AgentAPIClient(Base):
    __tablename__ = "agent_api_clients"
    __table_args__ = (
        CheckConstraint("permission = 'invoke'", name="ck_agent_api_clients_permission"),
    )

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_clients.id", ondelete="CASCADE"), primary_key=True
    )
    agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    permission: Mapped[str] = mapped_column(String(32), nullable=False, default="invoke")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    client: Mapped[APIClient] = relationship(back_populates="agent_bindings")
    agent: Mapped[Agent] = relationship(back_populates="api_client_bindings")


class APIKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'revoked')", name="ck_api_keys_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_clients.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="default")
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    client: Mapped[APIClient] = relationship(back_populates="api_keys")
    audit_logs: Mapped[list[AuditLog]] = relationship(back_populates="api_key")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'failed', 'rejected')",
            name="ck_audit_logs_status",
        ),
        CheckConstraint("latency_ms >= 0", name="ck_audit_logs_latency"),
        CheckConstraint("token_usage IS NULL OR token_usage >= 0", name="ck_audit_logs_token_usage"),
        CheckConstraint("mcp_call_count >= 0", name="ck_audit_logs_mcp_calls"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_clients.id", ondelete="SET NULL")
    )
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL")
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    token_usage: Mapped[int | None] = mapped_column(BigInteger)
    mcp_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    client: Mapped[APIClient | None] = relationship(back_populates="audit_logs")
    api_key: Mapped[APIKey | None] = relationship(back_populates="audit_logs")
    agent: Mapped[Agent | None] = relationship(back_populates="audit_logs")


class AgentMetric(Base):
    __tablename__ = "agent_metrics"
    __table_args__ = (
        UniqueConstraint("agent_id", "metric_date", name="uq_agent_metrics_agent_date"),
        CheckConstraint(
            "call_count >= 0 AND success_count >= 0 AND failure_count >= 0",
            name="ck_agent_metrics_call_counts",
        ),
        CheckConstraint(
            "total_latency_ms >= 0 AND total_token_usage >= 0 AND "
            "token_usage_observed_count >= 0 AND mcp_call_count >= 0",
            name="ck_agent_metrics_totals",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    call_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_latency_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_token_usage: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    token_usage_observed_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    mcp_call_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    agent: Mapped[Agent] = relationship(back_populates="metrics")


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),
        CheckConstraint(
            "status IN ('development', 'testing', 'release_candidate', 'published', 'deprecated')",
            name="ck_agent_versions_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="development")
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent: Mapped[Agent] = relationship(back_populates="versions", foreign_keys=[agent_id])
    executions: Mapped[list[ExecutionLog]] = relationship(
        back_populates="agent_version", foreign_keys="ExecutionLog.agent_version_id"
    )


class ModelRegistration(Base):
    __tablename__ = "model_registrations"
    __table_args__ = (
        CheckConstraint(
            "adapter IN ('hermes', 'qwen', 'deepseek', 'gpt', 'claude')",
            name="ck_model_registrations_adapter",
        ),
        CheckConstraint(
            "status IN ('unknown', 'online', 'offline')",
            name="ck_model_registrations_status",
        ),
        CheckConstraint("timeout_seconds BETWEEN 5 AND 1800", name="ck_model_registrations_timeout"),
        CheckConstraint("max_retries BETWEEN 0 AND 5", name="ck_model_registrations_retries"),
        CheckConstraint("NOT is_default OR is_enabled", name="ck_model_registrations_default_enabled"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="custom")
    adapter: Mapped[str] = mapped_column(String(32), nullable=False, default="hermes")
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    upstream_model: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key_ciphertext: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    @property
    def api_key_configured(self) -> bool:
        return bool(self.api_key_ciphertext)
