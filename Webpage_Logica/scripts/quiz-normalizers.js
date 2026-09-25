/*
 * Normalizzazione dei contratti API nei modelli uniformi usati dal renderer.
 */
(function exposeQuizNormalizers(global) {
    'use strict';

    function create(dependencies) {
        const shuffle = dependencies.shuffle;
        const prologToLogical = dependencies.prologToLogical;
        const normalizeGenerationSteps = dependencies.normalizeGenerationSteps;
        const extractWrongStepsMap = dependencies.extractWrongStepsMap;
        const normalizeConstruction = typeof dependencies.normalizeConstruction === 'function'
            ? dependencies.normalizeConstruction
            : function() { return null; };
        const buildConstructionFromFormula = typeof dependencies.buildConstructionFromFormula === 'function'
            ? dependencies.buildConstructionFromFormula
            : function() { return null; };
        const buildQuantifiedConstruction = typeof dependencies.buildQuantifiedConstruction === 'function'
            ? dependencies.buildQuantifiedConstruction
            : function() { return null; };
        const normalizeTransformation = typeof dependencies.normalizeTransformation === 'function'
            ? dependencies.normalizeTransformation
            : function() { return null; };
        const removeFormulaNegations = typeof dependencies.removeFormulaNegations === 'function'
            ? dependencies.removeFormulaNegations
            : function(formula) { return String(formula || ''); };

    function formatTruthInfo(entry) {
        if (typeof entry !== 'string') return '';
        const parts = entry.split('-');
        if (parts.length !== 2) return entry;
        const name = parts[0];
        const value = parts[1] === 'true' ? 'vero' : 'falso';
        return name + ' è ' + value;
    }

    function optionTextFromEntry(entry) {
        if (typeof entry === 'string') return String(entry || '').trim();
        if (!entry || typeof entry !== 'object') return '';
        return String(entry.formula_prolog || entry.formula || entry.text || '').trim();
    }

    function optionBooleanFlag(entry, keys) {
        if (!entry || typeof entry !== 'object' || !Array.isArray(keys)) return null;
        for (let i = 0; i < keys.length; i += 1) {
            const key = keys[i];
            if (!Object.prototype.hasOwnProperty.call(entry, key)) continue;
            const value = entry[key];
            if (typeof value === 'boolean') return value;
            if (value === 1 || value === '1' || value === 'true') return true;
            if (value === 0 || value === '0' || value === 'false') return false;
        }
        return null;
    }

    function optionConstruction(entry, formula) {
        const explicit = entry && typeof entry === 'object'
            ? normalizeConstruction(entry.construction)
            : null;
        return explicit || buildConstructionFromFormula(formula);
    }

    function optionTransformation(entry, formula) {
        if (!entry || typeof entry !== 'object') return null;
        const trace = normalizeTransformation(entry.transformation);
        const optionFormula = String(formula || '').trim();
        if (!trace || (optionFormula && trace.final_formula_prolog !== optionFormula)) return null;
        return trace;
    }

    function extractOptionsArray(res) {
        if (!res || typeof res !== 'object') return [];
        if (Array.isArray(res.options)) return res.options;
        if (Array.isArray(res.options_prolog)) return res.options_prolog;
        return [];
    }

    function pickGeneratorResult(payload, nestedKey) {
        if (!payload || typeof payload !== 'object') return payload;
        if (payload.result && typeof payload.result === 'object') {
            return payload.result;
        }
        if (nestedKey && payload[nestedKey] && typeof payload[nestedKey] === 'object') {
            return payload[nestedKey];
        }
        return payload;
    }

    // Normalizza il payload equivalenza in un formato uniforme per il renderer quiz.
    function normalizeEquivalenceResult(payload) {
        const res = pickGeneratorResult(payload, 'build_ex_depth');
        const optionsFromPayload = extractOptionsArray(res);
        const questionSource =
            (res && res.question_prolog) ||
            (res && res.original_formula && res.original_formula.formula_prolog) ||
            '';

        const fallbackQuestion = questionSource
            ? 'Quale formula è equivalente a "' + prologToLogical(questionSource) + '":'
            : 'Seleziona una formula dall\'esercizio ricevuto:';

        const normalizedOptionsFromArray = optionsFromPayload.map(function(entry) {
            const explicitCorrect = optionBooleanFlag(entry, ['is_correct', 'correct']);
            const text = optionTextFromEntry(entry);
            return {
                text: text,
                correct: explicitCorrect === null ? null : explicitCorrect,
                formulaSteps: normalizeGenerationSteps(entry && entry.generation_steps),
                construction: optionConstruction(entry, text),
                transformation: optionTransformation(entry, text)
            };
        }).filter(function(entry) {
            return Boolean(entry.text);
        });

        const questionStepsRaw =
            (res && res.original_formula && res.original_formula.generation_steps) ||
            [];
        let options = [];
        if (normalizedOptionsFromArray.length > 0) {
            options = normalizedOptionsFromArray;
        } else {
            const correct =
                (res && res.correct_answer_prolog) ||
                (res && res.modified_formula && res.modified_formula.formula_prolog) ||
                '';
            const wrongs =
                (res && Array.isArray(res.wrong_answers_prolog) && res.wrong_answers_prolog) ||
                [];
            const allCandidateOptions = Array.from(new Set((correct ? [correct] : []).concat(wrongs))).filter(Boolean);
            if (allCandidateOptions.length === 0) {
                return null;
            }
            const correctStepsRaw =
                (res && res.correct_answer_generation_steps) ||
                (res && res.modified_formula && res.modified_formula.generation_steps) ||
                [];
            const wrongStepsMapRaw = extractWrongStepsMap(res, allCandidateOptions);
            const wrongConstructionMap = {};
            const wrongTransformationMap = {};
            if (res && typeof res === 'object') {
                Object.keys(res).forEach(function(key) {
                    if (!/^distraction_\d+$/.test(key)) return;
                    const entry = res[key];
                    const formula = optionTextFromEntry(entry);
                    if (formula) {
                        wrongConstructionMap[formula] = optionConstruction(entry, formula);
                        wrongTransformationMap[formula] = optionTransformation(entry, formula);
                    }
                });
            }
            options = allCandidateOptions.map(function(candidateFormula) {
                const isCorrect = correct ? candidateFormula === correct : null;
                return {
                    text: candidateFormula,
                    correct: isCorrect,
                    formulaSteps: isCorrect === true
                        ? normalizeGenerationSteps(correctStepsRaw)
                        : normalizeGenerationSteps(wrongStepsMapRaw[candidateFormula]),
                    construction: isCorrect === true
                        ? optionConstruction(res && res.modified_formula, candidateFormula)
                        : (wrongConstructionMap[candidateFormula] || buildConstructionFromFormula(candidateFormula)),
                    transformation: isCorrect === true
                        ? optionTransformation(res && res.modified_formula, candidateFormula)
                        : (wrongTransformationMap[candidateFormula] || null)
                };
            });
        }

        if (options.length === 0) {
            return null;
        }

        const correctOption = options.find(function(entry) { return entry && entry.correct === true; });

        const imageFormulaSteps = {
            question: normalizeGenerationSteps(questionStepsRaw),
            correct: normalizeGenerationSteps(correctOption && correctOption.formulaSteps),
            wrongByFormula: {}
        };

        if (imageFormulaSteps.question.length === 0 && questionSource) {
            imageFormulaSteps.question = [questionSource];
        }
        if (imageFormulaSteps.correct.length === 0 && correctOption) {
            imageFormulaSteps.correct = [correctOption.text];
        }
        options.forEach(function(option) {
            if (!option || option.correct === true) return;
            const steps = Array.isArray(option.formulaSteps) ? option.formulaSteps.slice() : [];
            imageFormulaSteps.wrongByFormula[option.text] = steps.length > 0 ? steps : [option.text];
        });

        return {
            kind: 'equivalence',
            questionId: String((res && res.question_id) || ''),
            question: fallbackQuestion,
            info: [],
            options: shuffle(options),
            imageFormulaSteps: imageFormulaSteps,
            questionConstruction: optionConstruction(res && res.original_formula, questionSource)
        };
    }

    /**
     * Normalizza il payload backend per esercizi sul valore di verita.
     * @pre payload segue il contratto API truth-value (result/options/information/count).
     * @post Restituisce oggetto quiz standard o null se il payload e invalido.
     */
    function normalizeTruthValueResult(payload) {
        const res = pickGeneratorResult(payload, 'build_tvq');
        const options = extractOptionsArray(res);
        const info = (res && Array.isArray(res.information) && res.information) || [];

        if (options.length !== 4 || info.length < 3 || info.length > 5) {
            return null;
        }

        const parsedOptions = options.map(function(option) {
            const text = optionTextFromEntry(option);
            return {
                text: text,
                isTrue: optionBooleanFlag(option, ['is_true', 'truth_value']),
                construction: optionConstruction(option, text),
                transformation: optionTransformation(option, text)
            };
        });

        if (parsedOptions.some(function(option) {
            return !option.text || typeof option.isTrue !== 'boolean';
        })) {
            return null;
        }

        const trueCount = parsedOptions.filter(function(option) { return option.isTrue; }).length;
        const falseCount = parsedOptions.length - trueCount;

        let targetTruthValue = null;
        let question = '';
        if (trueCount === 1 && falseCount === 3) {
            targetTruthValue = true;
            question = 'Quale formula è vera tra le seguenti?';
        } else if (trueCount === 3 && falseCount === 1) {
            targetTruthValue = false;
            question = 'Quale formula è falsa tra le seguenti?';
        } else {
            return null;
        }

        const normalizedOptions = shuffle(parsedOptions.map(function(option) {
            return {
                text: option.text,
                correct: option.isTrue === targetTruthValue,
                construction: option.construction,
                transformation: option.transformation
            };
        }));

        return {
            kind: 'truth-value',
            questionId: String((res && res.question_id) || ''),
            question: question,
            info: info.map(formatTruthInfo),
            options: normalizedOptions
        };
    }

    /**
     * Normalizza il payload backend per esercizi di conseguenza logica.
     * @pre payload segue il contratto API logical-consequence (question/options).
     * @post Restituisce oggetto quiz standard o null se il payload e invalido.
     */
    function normalizeLogicalConsequenceResult(payload) {
        const res = pickGeneratorResult(payload, 'build_logical_consequence_question');
        if (!res || typeof res !== 'object') return null;

        const question = String(res.question_prolog || '').trim();
        let allOptions = extractOptionsArray(res);
        const correctOptions = Array.isArray(res.correct_options) ? res.correct_options : [];
        const wrongOptions = Array.isArray(res.wrong_options) ? res.wrong_options : [];

        // Fallback: some payloads may omit `options` and provide split arrays only.
        if (!allOptions.length && (correctOptions.length || wrongOptions.length)) {
            allOptions = correctOptions.concat(wrongOptions);
        }

        const correctFormulaSet = new Set(correctOptions.map(function(entry) {
            return optionTextFromEntry(entry);
        }).filter(Boolean));

        const normalizedOptions = allOptions.map(function(optionFormula) {
            const text = optionTextFromEntry(optionFormula);
            const explicitFlag = optionBooleanFlag(optionFormula, ['is_correct', 'correct', 'is_consequence', 'consequence']);
            const inferredCorrect = correctFormulaSet.has(text);
            return {
                text: text,
                correct: explicitFlag === true || inferredCorrect,
                construction: optionConstruction(optionFormula, text),
                transformation: optionTransformation(optionFormula, text)
            };
        }).filter(function(option) {
            return Boolean(option.text);
        });

        if (!question || normalizedOptions.length < 2 || !normalizedOptions.some(function(option) { return option.correct; })) {
            return null;
        }

        return {
            kind: 'logical-consequence',
            questionId: String((res && res.question_id) || ''),
            question: 'Quale formula è conseguenza logica di "' + prologToLogical(question) + '":',
            info: [],
            options: shuffle(normalizedOptions),
            questionConstruction: optionConstruction(res.question_formula, question)
        };
    }

    function bindPropositionalAtoms(formula, boundVariable) {
        const variable = String(boundVariable || 'x').trim().toLowerCase() || 'x';
        const reserved = new Set(['and', 'or', 'not', 'imp', 'iff', 'equiv', 'forall', 'exists', 'true', 'false']);
        return String(formula || '').replace(/\b([A-Za-z][A-Za-z0-9_]*)\b/g, function(token, _name, offset, source) {
            const lower = token.toLowerCase();
            if (reserved.has(lower)) return token;

            const tail = source.slice(offset + token.length);
            if (/^\s*\(/.test(tail)) return token;

            const prefix = source.slice(0, offset);
            if (lower === variable && /[A-Za-z][A-Za-z0-9_]*\(\s*$/.test(prefix)) return token;

            return token.charAt(0).toUpperCase() + token.slice(1) + '(' + variable + ')';
        });
    }

    /**
     * Genera opzioni multiple-choice per negazione di formule quantificate.
     * @pre quantifier e '∀' o '∃'; baseFormula e una formula testuale;
     *      spokenMode richiede una base positiva ricavata strutturalmente.
     * @post Restituisce domanda e 3 opzioni con esattamente una risposta corretta.
     */
    function buildQuantifiedNegationOptions(quantifier, baseFormula, baseFormulaSource, spokenMode) {
        const boundVariable = 'x';
        const rawFormulaSource = String(baseFormulaSource || '').trim();
        const preparedFormulaSource = spokenMode
            ? removeFormulaNegations(rawFormulaSource)
            : rawFormulaSource;
        const preparedDisplayFormula = spokenMode && preparedFormulaSource
            ? prologToLogical(preparedFormulaSource)
            : String(baseFormula || '').trim();
        const normalizedFormula = bindPropositionalAtoms(
            preparedDisplayFormula || 'p',
            boundVariable
        );
        const predicateFormulaSource = bindPropositionalAtoms(preparedFormulaSource, boundVariable);
        const wrappedFormula = '(' + normalizedFormula + ')';
        const isUniversal = quantifier === '∀';
        const original = quantifier + boundVariable + ' ' + wrappedFormula;
        const correct = isUniversal
            ? '∃' + boundVariable + ' ¬' + wrappedFormula
            : '∀' + boundVariable + ' ¬' + wrappedFormula;

        const wrongs = isUniversal
            ? [
                '∀' + boundVariable + ' ¬' + wrappedFormula,
                '∃' + boundVariable + ' ' + wrappedFormula
            ]
            : [
                '∃' + boundVariable + ' ¬' + wrappedFormula,
                '∀' + boundVariable + ' ' + wrappedFormula
            ];

        function quantifiedOption(text, optionQuantifier, negated) {
            return {
                text: text,
                correct: text === correct,
                construction: buildQuantifiedConstruction(
                    optionQuantifier,
                    normalizedFormula,
                    negated,
                    text,
                    predicateFormulaSource
                ),
                transformation: null
            };
        }

        const quantifiedOptions = isUniversal
            ? [
                quantifiedOption(correct, '∃', true),
                quantifiedOption(wrongs[0], '∀', true),
                quantifiedOption(wrongs[1], '∃', false)
            ]
            : [
                quantifiedOption(correct, '∀', true),
                quantifiedOption(wrongs[0], '∃', true),
                quantifiedOption(wrongs[1], '∀', false)
            ];

        return {
            question: 'Qual\'è la negazione di "' + original + '"?',
            options: shuffle(quantifiedOptions)
        };
    }

    function normalizeTranslationResult(payload) {
        const res = pickGeneratorResult(payload, 'build_translation_question');
        if (!res || typeof res !== 'object') return null;

        const question = String(res.question_text || res.question || '').trim();
        const info = Array.isArray(res.info) ? res.info.map(function(entry) {
            return String(entry || '').trim();
        }).filter(Boolean) : [];
        const allOptions = extractOptionsArray(res);
        const normalizedOptions = allOptions.map(function(optionFormula) {
            const text = optionTextFromEntry(optionFormula);
            return {
                text: text,
                correct: optionBooleanFlag(optionFormula, ['is_correct', 'correct']) === true,
                construction: optionConstruction(optionFormula, text),
                transformation: optionTransformation(optionFormula, text)
            };
        }).filter(function(option) {
            return Boolean(option.text);
        });

        if (!question || normalizedOptions.length < 2 || !normalizedOptions.some(function(option) { return option.correct; })) {
            return null;
        }

        return {
            kind: 'translation',
            questionId: String((res && res.question_id) || ''),
            question: question,
            info: info,
            options: shuffle(normalizedOptions)
        };
    }
        return {
            normalizeEquivalenceResult: normalizeEquivalenceResult,
            normalizeTruthValueResult: normalizeTruthValueResult,
            normalizeLogicalConsequenceResult: normalizeLogicalConsequenceResult,
            normalizeTranslationResult: normalizeTranslationResult,
            buildQuantifiedNegationOptions: buildQuantifiedNegationOptions
        };
    }

    global.LogicQuizNormalizers = Object.freeze({
        create: create
    });
})(window);
