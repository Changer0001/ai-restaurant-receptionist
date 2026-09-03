"""Per-restaurant voice settings

Two things that were global but must vary per restaurant if onboarding a
new client is to be "load their data and go":

- stt_vocabulary: the dish names fed to speech recognition as a hint. A
  global list of one cuisine's dish names actively harms every other
  cuisine — it biases the recogniser toward words the caller didn't say.
- takes_reservations: whether the AI collects booking details itself or
  hands off to a person. Nullable, so NULL keeps the deployment-wide
  default and only an explicit choice overrides it.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-03 12:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("restaurants", sa.Column("stt_vocabulary", sa.Text(), nullable=True))
    op.add_column("restaurants", sa.Column("takes_reservations", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("restaurants", "takes_reservations")
    op.drop_column("restaurants", "stt_vocabulary")
