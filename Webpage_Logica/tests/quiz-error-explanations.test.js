const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const quizSource = fs.readFileSync('scripts/quiz.js', 'utf8');
const exerciseHtml = fs.readFileSync('esercizi/esercitazione.html', 'utf8');

function extractFunction(source, name) {
    const start = source.indexOf('function ' + name + '(');
    assert.ok(start >= 0, 'funzione non trovata: ' + name);
    const bodyStart = source.indexOf('{', start);
    let depth = 0;
    for (let index = bodyStart; index < source.length; index += 1) {
        if (source[index] === '{') depth += 1;
        if (source[index] === '}') depth -= 1;
        if (depth === 0) return source.slice(start, index + 1);
    }
    throw new Error('corpo funzione non terminato: ' + name);
}

class FakeImageElement {
    constructor(tagName) {
        this.tagName = tagName;
        this.children = [];
        this.attributes = new Map();
        this.hidden = false;
        this.id = '';
        this.textContent = '';
        this.type = '';
        this.className = '';
        this.listeners = new Map();
    }

    appendChild(child) {
        if (child.tagName === '#fragment') {
            child.children.splice(0).forEach(item => this.appendChild(item));
            return child;
        }
        this.children.push(child);
        return child;
    }

    get childElementCount() {
        return this.children.length;
    }

    setAttribute(name, value) {
        this.attributes.set(name, String(value));
    }

    getAttribute(name) {
        return this.attributes.get(name) ?? null;
    }

    addEventListener(name, listener) {
        this.listeners.set(name, listener);
    }

    dispatch(name) {
        this.listeners.get(name)?.();
    }
}

test('a load failure exposes and focuses the existing main-menu navigation', () => {
    const loadStart = quizSource.indexOf('async function loadExercise()');
    const catchStart = quizSource.indexOf('} catch (err) {', loadStart);
    const loadEnd = quizSource.indexOf('function normalizeQuestionResult', catchStart);
    const errorBlock = quizSource.slice(catchStart, loadEnd);

    assert.ok(loadStart >= 0 && catchStart > loadStart && loadEnd > catchStart);
    assert.match(errorBlock, /state\.mode = 'error';/);
    assert.match(errorBlock, /actionButton\.disabled = true;/);
    assert.match(errorBlock, /quizTimer\.stop\(\);\s*quizTimer\.hide\(\);/);
    assert.match(errorBlock, /indexNavEl\.hidden = false;/);
    assert.match(errorBlock, /querySelector\('a\[href="\/"\], a\[href="\.\.\/index\.html"\]'\)/);
    assert.match(errorBlock, /mainMenuLink\.textContent = 'Torna al menu principale';/);
    assert.match(errorBlock, /mainMenuLink\.focus\(\)/);
});

test('formula transformation is rendered before optional answer images', () => {
    const checkStart = quizSource.indexOf('function checkAnswer()');
    const checkEnd = quizSource.indexOf('function renderReview()', checkStart);
    const checkBlock = quizSource.slice(checkStart, checkEnd);
    const transformationIndex = checkBlock.indexOf('showFormulaTransformation({');
    const imagesIndex = checkBlock.indexOf('renderWrongActionImages();');

    assert.ok(checkStart >= 0 && checkEnd > checkStart);
    assert.ok(transformationIndex >= 0);
    assert.ok(imagesIndex > transformationIndex);
    assert.match(checkBlock, /try \{\s*renderWrongActionImages\(\);\s*\} catch \(imageError\)/);

    const transformationMarkupIndex = exerciseHtml.indexOf('id="quizFormulaTransformation"');
    const imagesMarkupIndex = exerciseHtml.indexOf('id="quizWrongActionImages"');
    assert.ok(transformationMarkupIndex >= 0);
    assert.ok(imagesMarkupIndex > transformationMarkupIndex);
});

test('rendered answer images have an accessible hide and reopen control', () => {
    const css = fs.readFileSync('styles/quiz-images.css', 'utf8');
    const renderStart = quizSource.indexOf('function renderWrongActionImages()');
    const renderEnd = quizSource.indexOf('function syncWrongImagesAvailability()', renderStart);
    const renderBlock = quizSource.slice(renderStart, renderEnd);

    assert.ok(renderStart >= 0 && renderEnd > renderStart);
    assert.match(renderBlock, /toggle\.textContent = 'Nascondi le immagini'/);
    assert.match(renderBlock, /toggle\.setAttribute\('aria-expanded', 'true'\)/);
    assert.match(renderBlock, /toggle\.setAttribute\('aria-controls', panelId\)/);
    assert.match(renderBlock, /panel\.hidden = !willOpen/);
    assert.match(renderBlock, /willOpen \? 'Nascondi le immagini' : 'Mostra le immagini'/);
    assert.match(renderBlock, /toggle\.setAttribute\('aria-expanded', willOpen \? 'true' : 'false'\)/);
    assert.match(css, /\.quiz-wrong-images-panel\[hidden\]\s*\{[\s\S]*?display:\s*none/);
    assert.match(css, /\.quiz-wrong-images-toggle:focus-visible/);
});

test('image disclosure behavior keeps hidden state, label and ARIA state synchronized', () => {
    const container = new FakeImageElement('div');
    container.hidden = true;
    const context = {
        state: {
            showWrongActionImages: true,
            spokenlanguage: true,
            selectedIndex: 0,
            correctIndex: 1,
            options: [{ text: 'and(p,q)' }, { text: 'and(q,p)' }]
        },
        wrongActionImagesEl: container,
        currentQuestionText: 'and(p,q)',
        currentImageFormulaSteps: { question: [], correct: [], wrongByFormula: {} },
        imagePanelSequence: 0,
        clearWrongActionImages() {
            container.children.length = 0;
            container.hidden = true;
        },
        isDayMode: () => false,
        extractFormulaFromQuestionText: text => text,
        getOptionDisplayFormula: option => option.text,
        buildImageFileDescriptors: () => [{ key: 'question', title: 'Domanda', formulaText: 'and(p,q)' }],
        getCachedFormulaSequence: () => [],
        renderImageFileSection(parent) {
            parent.appendChild(new FakeImageElement('section'));
        },
        document: {
            createDocumentFragment: () => new FakeImageElement('#fragment'),
            createElement: tagName => new FakeImageElement(tagName)
        }
    };
    const render = vm.runInNewContext(
        '(' + extractFunction(quizSource, 'renderWrongActionImages') + ')',
        context
    );

    render();

    assert.equal(container.hidden, false);
    assert.equal(container.children.length, 2);
    const [toggle, panel] = container.children;
    assert.equal(toggle.type, 'button');
    assert.equal(toggle.textContent, 'Nascondi le immagini');
    assert.equal(toggle.getAttribute('aria-expanded'), 'true');
    assert.equal(toggle.getAttribute('aria-controls'), panel.id);
    assert.equal(panel.hidden, false);
    assert.equal(panel.getAttribute('role'), 'region');

    toggle.dispatch('click');

    assert.equal(panel.hidden, true);
    assert.equal(toggle.textContent, 'Mostra le immagini');
    assert.equal(toggle.getAttribute('aria-expanded'), 'false');

    toggle.dispatch('click');

    assert.equal(panel.hidden, false);
    assert.equal(toggle.textContent, 'Nascondi le immagini');
    assert.equal(toggle.getAttribute('aria-expanded'), 'true');
});
