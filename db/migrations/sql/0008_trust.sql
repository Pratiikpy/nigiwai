-- 0008 trust: the owner waitlist and the usefulness feedback (M25).

-- The waitlist holds an owner's email and the consent text they saw, and nothing else. It has no tenant and no link to any
-- survey data, and the application role can only add to it: it cannot read or change it.
CREATE TABLE waitlist (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL CHECK (char_length(email) <= 254),
  email_key text NOT NULL UNIQUE,
  consent_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
GRANT INSERT ON waitlist TO nigiwai_app;

-- "Was this useful?" on a Soundcheck or a Booking Brief. Stored without the account, the venue or the person: the only
-- columns are what was rated, the answer, an optional line of text and when.
CREATE TABLE feedback (
  id bigserial PRIMARY KEY,
  kind text NOT NULL CHECK (kind IN ('soundcheck', 'brief')),
  useful boolean NOT NULL,
  note text CHECK (char_length(note) <= 280),
  created_at timestamptz NOT NULL DEFAULT now()
);
GRANT INSERT ON feedback TO nigiwai_app;
GRANT USAGE ON SEQUENCE feedback_id_seq TO nigiwai_app;
