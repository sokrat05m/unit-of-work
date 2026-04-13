from collections.abc import Iterable
from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest

from uow import (
    EntityConfig,
    GenericDataMapper,
    InstrumentationRegistry,
    ListOf,
    SetOf,
    UnitOfWork,
)


# ── Domain objects ──────────────────────────────────────────────


@dataclass
class Comment:
    text: str


@dataclass(unsafe_hash=True)
class Tag:
    label: str


@dataclass
class Post:
    id: int | None
    title: str
    comments: list[Comment] = field(default_factory=list)
    tags: set[Tag] = field(default_factory=set)


# ── Fake mappers ────────────────────────────────────────────────


class FakePostMapper(GenericDataMapper[Post]):
    def __init__(self, connection: object) -> None:
        self.saved: list[Post] = []

    async def save(self, entities: Iterable[Post]) -> None:
        self.saved.extend(entities)

    async def update(self, entities: Iterable[Post]) -> None: ...
    async def delete(self, entities: Iterable[Post]) -> None: ...


class FakeCommentMapper(GenericDataMapper[Comment]):
    def __init__(self, connection: object) -> None:
        self.saved: list[Comment] = []

    async def save(self, entities: Iterable[Comment]) -> None:
        self.saved.extend(entities)

    async def update(self, entities: Iterable[Comment]) -> None: ...
    async def delete(self, entities: Iterable[Comment]) -> None: ...


class FakeTagMapper(GenericDataMapper[Tag]):
    def __init__(self, connection: object) -> None:
        self.saved: list[Tag] = []

    async def save(self, entities: Iterable[Tag]) -> None:
        self.saved.extend(entities)

    async def update(self, entities: Iterable[Tag]) -> None: ...
    async def delete(self, entities: Iterable[Tag]) -> None: ...


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def registry() -> InstrumentationRegistry:
    reg = InstrumentationRegistry()
    reg.register(
        EntityConfig(
            entity_type=Post,
            identity_key=("id",),
            mapper_type=FakePostMapper,
            children={
                "comments": ListOf(Comment, parent_key="post_id"),
                "tags": SetOf(Tag, parent_key="post_id"),
            },
        )
    )
    reg.register(
        EntityConfig(
            entity_type=Comment,
            identity_key=("post_id", "text"),
            mapper_type=FakeCommentMapper,
            depends_on=[Post],
        )
    )
    reg.register(
        EntityConfig(
            entity_type=Tag,
            identity_key=("post_id", "label"),
            mapper_type=FakeTagMapper,
            depends_on=[Post],
        )
    )
    return reg


@pytest.fixture
def uow(registry: InstrumentationRegistry) -> UnitOfWork:
    return UnitOfWork(AsyncMock(), registry)


# ── Tests ───────────────────────────────────────────────────────


class TestParentKeyListOf:
    def test_register_new_sets_parent_key_on_initial_children(
        self, uow: UnitOfWork
    ) -> None:
        comment = Comment(text="hello")
        post = Post(id=42, title="T", comments=[comment])
        uow.register_new(post)

        assert comment.post_id == 42  # type: ignore[attr-defined]

    def test_append_sets_parent_key(self, uow: UnitOfWork) -> None:
        post = Post(id=7, title="T")
        uow.register_clean(post)

        comment = Comment(text="new")
        post.comments.append(comment)

        assert comment.post_id == 7  # type: ignore[attr-defined]

    def test_insert_sets_parent_key(self, uow: UnitOfWork) -> None:
        post = Post(id=5, title="T")
        uow.register_clean(post)

        comment = Comment(text="inserted")
        post.comments.insert(0, comment)

        assert comment.post_id == 5  # type: ignore[attr-defined]

    def test_extend_sets_parent_key(self, uow: UnitOfWork) -> None:
        post = Post(id=3, title="T")
        uow.register_clean(post)

        c1 = Comment(text="a")
        c2 = Comment(text="b")
        post.comments.extend([c1, c2])

        assert c1.post_id == 3  # type: ignore[attr-defined]
        assert c2.post_id == 3  # type: ignore[attr-defined]


class TestParentKeySetOf:
    def test_register_new_sets_parent_key_on_initial_children(
        self, uow: UnitOfWork
    ) -> None:
        tag = Tag(label="python")
        post = Post(id=10, title="T", tags={tag})
        uow.register_new(post)

        assert tag.post_id == 10  # type: ignore[attr-defined]

    def test_add_sets_parent_key(self, uow: UnitOfWork) -> None:
        post = Post(id=8, title="T")
        uow.register_clean(post)

        tag = Tag(label="rust")
        post.tags.add(tag)

        assert tag.post_id == 8  # type: ignore[attr-defined]


class TestParentKeyNone:
    def test_no_parent_key_does_not_set_attr(self) -> None:
        reg = InstrumentationRegistry()
        reg.register(
            EntityConfig(
                entity_type=Post,
                identity_key=("id",),
                mapper_type=FakePostMapper,
                children={"comments": ListOf(Comment)},
            )
        )
        reg.register(
            EntityConfig(
                entity_type=Comment,
                identity_key=("text",),
                mapper_type=FakeCommentMapper,
                depends_on=[Post],
            )
        )
        uow = UnitOfWork(AsyncMock(), reg)

        comment = Comment(text="hello")
        post = Post(id=42, title="T", comments=[comment])
        uow.register_new(post)

        assert not hasattr(comment, "post_id")


class TestParentKeyFlush:
    @pytest.mark.asyncio
    async def test_parent_key_available_at_flush(self, uow: UnitOfWork) -> None:
        post = Post(id=99, title="T")
        uow.register_new(post)

        comment = Comment(text="flushed")
        post.comments.append(comment)

        await uow.flush()

        mapper = uow._mappers[Comment]
        assert isinstance(mapper, FakeCommentMapper)
        assert len(mapper.saved) == 1
        assert mapper.saved[0].post_id == 99  # type: ignore[attr-defined]
