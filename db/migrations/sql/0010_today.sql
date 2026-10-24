-- 0010 today: what an owner decided about each action on the Today board (M5), and the moves they log (M11 builds on it).

-- One row per action an owner accepted or dismissed this week. The action itself is computed from stored data each time
-- the board is opened, so only the decision is kept, under a key that names what the action is about. No row means
-- undecided; undoing a decision deletes its row.
CREATE TABLE board_decision (
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  business_id uuid NOT NULL REFERENCES business(id) ON DELETE CASCADE,
  week text NOT NULL CHECK (week ~ '^[0-9]{4}-W[0-9]{2}$'),
  action_key text NOT NULL CHECK (char_length(action_key) BETWEEN 1 AND 120),
  state text NOT NULL CHECK (state IN ('accepted', 'dismissed')),
  decided_by uuid REFERENCES app_user(id) ON DELETE SET NULL,
  decided_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (business_id, week, action_key)
);

-- Something the owner changed, so scans before and after can be compared. Logged from an accepted action or by hand.
CREATE TABLE move (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
  business_id uuid NOT NULL REFERENCES business(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('act', 'event', 'menu', 'ad', 'price', 'other')),
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 160),
  started_on date NOT NULL,
  source text NOT NULL CHECK (source IN ('today', 'manual')),
  source_key text CHECK (char_length(source_key) <= 120),
  created_by uuid REFERENCES app_user(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (business_id, source, source_key)
);
CREATE INDEX move_business_idx ON move (business_id, started_on DESC);

ALTER TABLE board_decision ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON board_decision
  USING (tenant_id = current_tenant()) WITH CHECK (tenant_id = current_tenant());
ALTER TABLE move ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON move
  USING (tenant_id = current_tenant()) WITH CHECK (tenant_id = current_tenant());

GRANT SELECT, INSERT, UPDATE, DELETE ON board_decision, move TO nigiwai_app, nigiwai_worker;
