/* Esportazione sicura di risultati locali in JSON e CSV. */
(function exposeResultsExport(global) {
    'use strict';

    function safeCsvCell(value) {
        let text = String(value == null ? '' : value);
        if (/^[=+\-@]/.test(text)) text = "'" + text;
        return '"' + text.replace(/"/g, '""') + '"';
    }

    function toCsv(attempts) {
        const rows = [['Data', 'Tipologia', 'Difficoltà', 'Corretta', 'Tempo ms', 'Domanda', 'Risposta', 'Soluzione']];
        (Array.isArray(attempts) ? attempts : []).forEach(function(item) {
            rows.push([
                new Date(Number(item.answeredAt) || Date.now()).toISOString(),
                item.type,
                item.difficulty,
                item.correct ? 'Sì' : 'No',
                item.elapsedMs,
                item.question,
                item.selectedAnswer,
                item.correctAnswer
            ]);
        });
        return rows.map(function(row) { return row.map(safeCsvCell).join(','); }).join('\r\n');
    }

    function download(filename, content, mimeType) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    }

    global.LogicResultsExport = Object.freeze({
        downloadCsv: function(attempts) { download('testlogica-risultati.csv', toCsv(attempts), 'text/csv;charset=utf-8'); },
        downloadJson: function(data) {
            download('testlogica-risultati.json', JSON.stringify({
                version: 1,
                exportedAt: Date.now(),
                timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
                data: data
            }, null, 2), 'application/json');
        },
        safeCsvCell: safeCsvCell,
        toCsv: toCsv
    });
})(window);
