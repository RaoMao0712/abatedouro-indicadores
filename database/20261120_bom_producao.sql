BEGIN;

ALTER TABLE bom DROP CONSTRAINT ex_bom_vigencia;
ALTER TABLE bom DROP CONSTRAINT bom_status_check;
ALTER TABLE bom DROP COLUMN ativa;
ALTER TABLE bom ADD CONSTRAINT bom_status_check
    CHECK (status IN ('RASCUNHO', 'PUBLICADA', 'ATIVA', 'INATIVA'));
CREATE INDEX ix_bom_vigencia ON bom (produto_id, status, data_inicio_vigencia);
CREATE UNIQUE INDEX uq_bom_ativa_produto ON bom (produto_id) WHERE status = 'ATIVA';

CREATE FUNCTION proteger_versao_bom() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'RASCUNHO' THEN
            RAISE EXCEPTION 'A BOM deve iniciar em rascunho' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status = 'RASCUNHO' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        IF NEW.status IN ('RASCUNHO', 'PUBLICADA') THEN
            RETURN NEW;
        END IF;
    ELSIF TG_OP = 'UPDATE' THEN
        IF (to_jsonb(NEW) - ARRAY['status', 'atualizado_em', 'atualizado_por'])
            IS NOT DISTINCT FROM
            (to_jsonb(OLD) - ARRAY['status', 'atualizado_em', 'atualizado_por'])
            AND (
                (OLD.status = 'PUBLICADA' AND NEW.status IN ('ATIVA', 'INATIVA'))
                OR (OLD.status = 'ATIVA' AND NEW.status = 'INATIVA')
            ) THEN
            RETURN NEW;
        END IF;
    END IF;
    RAISE EXCEPTION 'Versão de BOM imutável ou transição inválida' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER trg_bom_versao BEFORE INSERT OR UPDATE OR DELETE ON bom
FOR EACH ROW EXECUTE FUNCTION proteger_versao_bom();

CREATE FUNCTION proteger_item_bom() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM 1 FROM bom WHERE id = OLD.bom_id AND status = 'RASCUNHO' FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Itens de BOM publicada são imutáveis' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM 1 FROM bom WHERE id = NEW.bom_id AND status = 'RASCUNHO' FOR SHARE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'Itens de BOM publicada são imutáveis' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    RETURN OLD;
END;
$$;

CREATE TRIGGER trg_bom_item BEFORE INSERT OR UPDATE OR DELETE ON bom_item
FOR EACH ROW EXECUTE FUNCTION proteger_item_bom();

COMMIT;
