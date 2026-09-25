/*
 * Contratto e descrizioni per i percorsi che trasformano una formula in un'altra.
 */
(function exposeFormulaTransformation(global) {
    'use strict';

    const VERSION = 1;
    const STRATEGIES = new Set(['equivalence_rewrite', 'distractor_mutation']);
    const STEP_KINDS = new Set(['rewrite', 'mutation']);
    const RULE_LABELS = Object.freeze({
        associativity_and: 'l\'associatività della congiunzione',
        associativity_or: 'l\'associatività della disgiunzione',
        biconditional_elimination: 'l\'eliminazione della doppia implicazione',
        biconditional_negation: 'la negazione simultanea dei membri della doppia implicazione',
        commutativity_and: 'la commutatività della congiunzione',
        commutativity_iff: 'la commutatività della doppia implicazione',
        commutativity_or: 'la commutatività della disgiunzione',
        de_morgan_and: 'la legge di De Morgan sulla congiunzione',
        de_morgan_or: 'la legge di De Morgan sulla disgiunzione',
        distribution_and_over_or: 'la distribuzione della congiunzione sulla disgiunzione',
        distribution_or_over_and: 'la distribuzione della disgiunzione sulla congiunzione',
        double_negation: 'l\'eliminazione della doppia negazione',
        implication_elimination: 'l\'eliminazione dell\'implicazione',
        idempotence_and: 'l\'idempotenza della congiunzione',
        idempotence_or: 'l\'idempotenza della disgiunzione',
        absorption_and: 'l\'assorbimento della congiunzione',
        absorption_or: 'l\'assorbimento della disgiunzione',
        identity_and: 'l\'identità della congiunzione',
        identity_or: 'l\'identità della disgiunzione',
        domination_and: 'la dominazione della congiunzione',
        domination_or: 'la dominazione della disgiunzione',
        constant_negation: 'la semplificazione della negazione di una costante',
        constant_implication: 'la semplificazione di un\'implicazione costante',
        constant_biconditional: 'la semplificazione di una doppia implicazione costante',
        complement_and: 'la legge del complemento nella congiunzione',
        complement_or: 'la legge del complemento nella disgiunzione',
        equivalent_rewrite: 'una riscrittura equivalente',
        replace_operator_and_with_or: 'la sostituzione della congiunzione con una disgiunzione',
        replace_operator_or_with_and: 'la sostituzione della disgiunzione con una congiunzione',
        replace_operator_imp_with_iff: 'la sostituzione dell\'implicazione con una doppia implicazione',
        replace_operator_iff_with_imp: 'la sostituzione della doppia implicazione con un\'implicazione',
        negate_atom: 'la negazione di un atomo',
        distractor_mutation: 'una modifica intenzionale non equivalente',
        distractor_operator_cycles: 'una sequenza di sostituzioni intenzionalmente non equivalenti'
    });
    const OPERATOR_LABELS = Object.freeze({
        atom: 'atomo',
        not: 'negazione',
        and: 'congiunzione',
        or: 'disgiunzione',
        imp: 'implicazione',
        iff: 'doppia implicazione'
    });
    const RULE_SCHEMAS = Object.freeze({
        associativity_and: '(A ∧ B) ∧ C ⇔ A ∧ (B ∧ C)',
        associativity_or: '(A ∨ B) ∨ C ⇔ A ∨ (B ∨ C)',
        biconditional_elimination: 'A ↔ B ⇔ (A → B) ∧ (B → A)',
        biconditional_negation: 'A ↔ B ⇔ (¬A ↔ ¬B)',
        commutativity_and: 'A ∧ B ⇔ B ∧ A',
        commutativity_iff: 'A ↔ B ⇔ B ↔ A',
        commutativity_or: 'A ∨ B ⇔ B ∨ A',
        de_morgan_and: '¬(A ∧ B) ⇔ ¬A ∨ ¬B',
        de_morgan_or: '¬(A ∨ B) ⇔ ¬A ∧ ¬B',
        distribution_and_over_or: 'A ∧ (B ∨ C) ⇔ (A ∧ B) ∨ (A ∧ C)',
        distribution_or_over_and: 'A ∨ (B ∧ C) ⇔ (A ∨ B) ∧ (A ∨ C)',
        double_negation: '¬¬A ⇔ A',
        implication_elimination: 'A → B ⇔ ¬A ∨ B',
        idempotence_and: 'A ∧ A ⇔ A',
        idempotence_or: 'A ∨ A ⇔ A',
        absorption_and: 'A ∧ (A ∨ B) ⇔ A',
        absorption_or: 'A ∨ (A ∧ B) ⇔ A',
        identity_and: 'A ∧ ⊤ ⇔ A',
        identity_or: 'A ∨ ⊥ ⇔ A',
        domination_and: 'A ∧ ⊥ ⇔ ⊥',
        domination_or: 'A ∨ ⊤ ⇔ ⊤',
        constant_negation: '¬⊤ ⇔ ⊥;  ¬⊥ ⇔ ⊤',
        constant_implication: '⊤ → A ⇔ A;  ⊥ → A ⇔ ⊤;  A → ⊤ ⇔ ⊤;  A → ⊥ ⇔ ¬A',
        constant_biconditional: '⊤ ↔ A ⇔ A;  ⊥ ↔ A ⇔ ¬A',
        complement_and: 'A ∧ ¬A ⇔ ⊥',
        complement_or: 'A ∨ ¬A ⇔ ⊤',
        equivalent_rewrite: 'Φ ⇔ Ψ',
        replace_operator_and_with_or: '(A ∧ B) ⟶ (A ∨ B)  (non equivalente)',
        replace_operator_or_with_and: '(A ∨ B) ⟶ (A ∧ B)  (non equivalente)',
        replace_operator_imp_with_iff: '(A → B) ⟶ (A ↔ B)  (non equivalente)',
        replace_operator_iff_with_imp: '(A ↔ B) ⟶ (A → B)  (non equivalente)',
        negate_atom: 'A ⟶ ¬A  (non equivalente)',
        distractor_mutation: 'Φ ⟶ Ψ  (non equivalente)',
        distractor_operator_cycles: 'Φ ⟶ Ψ  (non equivalente)'
    });
    const OPERATOR_SCHEMAS = Object.freeze({
        atom: 'A',
        not: '¬A',
        and: 'A ∧ B',
        or: 'A ∨ B',
        imp: 'A → B',
        iff: 'A ↔ B'
    });

    function cleanText(value) {
        return String(value == null ? '' : value).trim();
    }

    function normalize(raw) {
        if (!raw || typeof raw !== 'object' || Array.isArray(raw) || raw.version !== VERSION) {
            return null;
        }

        const strategy = cleanText(raw.strategy);
        const source = cleanText(raw.source_formula_prolog);
        const finalFormula = cleanText(raw.final_formula_prolog);
        if (!STRATEGIES.has(strategy) || !source || !finalFormula || typeof raw.preserves_meaning !== 'boolean') {
            return null;
        }
        if (strategy === 'equivalence_rewrite' && raw.preserves_meaning !== true) return null;
        if (strategy === 'distractor_mutation' && raw.preserves_meaning !== false) return null;
        if (!Array.isArray(raw.steps) || raw.steps.length === 0) return null;

        const steps = [];
        let expectedBefore = source;
        for (let position = 0; position < raw.steps.length; position += 1) {
            const item = raw.steps[position];
            if (!item || typeof item !== 'object' || Array.isArray(item)) return null;

            const index = item.index;
            const kind = cleanText(item.kind);
            const rule = cleanText(item.rule);
            const before = cleanText(item.before_prolog);
            const after = cleanText(item.after_prolog);
            const beforeSubformula = cleanText(item.before_subformula_prolog);
            const afterSubformula = cleanText(item.after_subformula_prolog);
            const location = cleanText(item.location);
            if (index !== position + 1 || !STEP_KINDS.has(kind) || !rule || !before || !after || !location) {
                return null;
            }
            if (before !== expectedBefore || before === after) return null;
            if (strategy === 'equivalence_rewrite' && kind !== 'rewrite') return null;
            if (strategy === 'distractor_mutation' && kind !== 'mutation') return null;

            // I payload precedenti non distinguevano la sottoformula riscritta
            // dalla formula completa. Una coppia parziale non e' utilizzabile:
            // in quel caso manteniamo il fallback compatibile e verificabile.
            const hasSubformulaPair = Boolean(beforeSubformula && afterSubformula);

            steps.push({
                index: index,
                kind: kind,
                rule: rule,
                before_prolog: before,
                after_prolog: after,
                before_subformula_prolog: hasSubformulaPair ? beforeSubformula : before,
                after_subformula_prolog: hasSubformulaPair ? afterSubformula : after,
                location: location
            });
            expectedBefore = after;
        }

        if (expectedBefore !== finalFormula) return null;
        return {
            version: VERSION,
            strategy: strategy,
            source_formula_prolog: source,
            final_formula_prolog: finalFormula,
            preserves_meaning: raw.preserves_meaning,
            steps: steps
        };
    }

    function locationSuffix(location) {
        const value = cleanText(location);
        if (!value || value === 'root') return ' all\'intera formula';
        const parts = value.split('.').slice(1).map(function(part) {
            if (part === 'left') return 'ramo sinistro';
            if (part === 'right') return 'ramo destro';
            if (part === 'operand') return 'operando della negazione';
            return 'sottoformula';
        });
        return parts.length ? ' nella sottoformula: ' + parts.join(', ') : ' nel passaggio indicato della formula';
    }

    function ruleLabel(rule) {
        if (RULE_LABELS[rule]) return RULE_LABELS[rule];
        const replacement = cleanText(rule).match(/^replace_operator_(atom|not|and|or|imp|iff)_with_(atom|not|and|or|imp|iff)$/);
        if (replacement) {
            return 'la sostituzione di ' + OPERATOR_LABELS[replacement[1]] + ' con ' + OPERATOR_LABELS[replacement[2]];
        }
        const wrapping = cleanText(rule).match(/^wrap_atom_with_(not|and|or|imp|iff)$/);
        if (wrapping) return 'l\'inserimento di un atomo in una ' + OPERATOR_LABELS[wrapping[1]];
        return '';
    }

    function ruleSchema(stepOrRule) {
        const step = stepOrRule && typeof stepOrRule === 'object' ? stepOrRule : null;
        const rule = cleanText(step ? step.rule : stepOrRule);
        if (RULE_SCHEMAS[rule]) return RULE_SCHEMAS[rule];

        const replacement = rule.match(/^replace_operator_(atom|not|and|or|imp|iff)_with_(atom|not|and|or|imp|iff)$/);
        if (replacement) {
            return '(' + OPERATOR_SCHEMAS[replacement[1]] + ') ⟶ ('
                + OPERATOR_SCHEMAS[replacement[2]] + ')  (non equivalente)';
        }
        const wrapping = rule.match(/^wrap_atom_with_(not|and|or|imp|iff)$/);
        if (wrapping) {
            return 'A ⟶ (' + OPERATOR_SCHEMAS[wrapping[1]] + ')  (non equivalente)';
        }
        return step && step.kind === 'mutation'
            ? 'Φ ⟶ Ψ  (non equivalente)'
            : 'Φ ⇔ Ψ';
    }

    function relationSymbol(step) {
        return step && step.kind === 'mutation' ? '⟶' : '⇔';
    }

    function describeStep(step) {
        if (!step || typeof step !== 'object') return 'Ottieni il passaggio successivo.';
        const label = ruleLabel(step.rule);
        if (label) {
            const verb = step.kind === 'mutation' ? 'Esegui ' : 'Applica ';
            return verb + label + locationSuffix(step.location) + '.';
        }
        if (step.kind === 'mutation') {
            return 'Modifica intenzionalmente il passaggio indicato: il risultato non è equivalente alla formula di partenza.';
        }
        return 'Applica una regola di equivalenza al passaggio indicato.';
    }

    global.LogicFormulaTransformation = Object.freeze({
        VERSION: VERSION,
        describeStep: describeStep,
        normalize: normalize,
        relationSymbol: relationSymbol,
        ruleLabel: ruleLabel,
        ruleSchema: ruleSchema
    });
})(window);
