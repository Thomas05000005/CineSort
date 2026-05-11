-- v11: renommage des tiers qualite vers la nomenclature premium
-- Premium -> Platinum, Bon -> Gold, Moyen -> Silver, Faible -> Bronze (score >= 30)
-- Nouveau tier Reject pour les scores < 30 (anciennement rangés dans "Faible").
-- Source : audit AUDIT_20260422 finding U1 (alignement sur la maquette v8-restraint).

-- quality_reports.tier
UPDATE quality_reports
   SET tier = CASE
       WHEN tier = 'Premium' THEN 'Platinum'
       WHEN tier = 'Bon'     THEN 'Gold'
       WHEN tier = 'Moyen'   THEN 'Silver'
       WHEN tier = 'Faible' AND score >= 30 THEN 'Bronze'
       WHEN tier = 'Faible' AND score <  30 THEN 'Reject'
       WHEN tier = 'Mauvais' AND score >= 30 THEN 'Bronze'
       WHEN tier = 'Mauvais' AND score <  30 THEN 'Reject'
       ELSE tier
   END
 WHERE tier IN ('Premium', 'Bon', 'Moyen', 'Faible', 'Mauvais');

PRAGMA user_version = 11;
