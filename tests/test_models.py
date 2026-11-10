from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Project, ProjectMembership, ProjectRole, User


def test_project_membership_persists_project_scoped_role() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        user = User(email="owner@example.test", password_hash="test-hash")
        project = Project(name="AURORA")
        session.add_all([user, project])
        session.flush()
        session.add(
            ProjectMembership(
                user_id=user.id,
                project_id=project.id,
                role=ProjectRole.OWNER,
            )
        )
        session.commit()

        membership = session.get(ProjectMembership, (project.id, user.id))
        assert membership is not None
        assert membership.role is ProjectRole.OWNER

    engine.dispose()
