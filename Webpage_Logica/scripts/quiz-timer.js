/*
 * Countdown del quiz con stato e scheduling incapsulati.
 */
(function exposeQuizTimer(global) {
    'use strict';

    function format(totalSeconds) {
        const safe = Math.max(0, Number(totalSeconds) || 0);
        const minutes = Math.floor(safe / 60);
        const seconds = safe % 60;
        return String(minutes).padStart(2, '0') + ':' + String(seconds).padStart(2, '0');
    }

    function create(options) {
        const display = options.display || null;
        const defaultMinutes = Number(options.defaultMinutes) || 20;
        const parseMinutes = options.parseMinutes;
        const onExpire = typeof options.onExpire === 'function' ? options.onExpire : function() {};
        const schedule = options.setInterval || global.setInterval.bind(global);
        const unschedule = options.clearInterval || global.clearInterval.bind(global);
        let secondsRemaining = defaultMinutes * 60;
        let intervalId = null;

        function render() {
            if (display) display.textContent = format(secondsRemaining);
        }

        function stop() {
            if (intervalId !== null) {
                unschedule(intervalId);
                intervalId = null;
            }
        }

        function reset(minutes) {
            stop();
            secondsRemaining = parseMinutes(minutes, defaultMinutes) * 60;
            render();
        }

        function start(minutes) {
            reset(minutes);
            startCountdown();
        }

        function startCountdown() {
            if (display) display.hidden = false;
            stop();
            intervalId = schedule(function() {
                secondsRemaining -= 1;
                if (secondsRemaining <= 0) {
                    secondsRemaining = 0;
                    render();
                    stop();
                    onExpire();
                    return;
                }
                render();
            }, 1000);
        }

        function startSeconds(seconds) {
            secondsRemaining = Math.max(0, Math.round(Number(seconds) || 0));
            render();
            startCountdown();
        }

        function hide() {
            if (display) display.hidden = true;
        }

        render();
        return Object.freeze({
            start: start,
            stop: stop,
            reset: reset,
            hide: hide,
            getRemainingSeconds: function() { return secondsRemaining; },
            startSeconds: startSeconds,
            format: format
        });
    }

    global.LogicQuizTimer = Object.freeze({ create: create, format: format });
})(window);
