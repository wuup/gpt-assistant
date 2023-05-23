
document.addEventListener('DOMContentLoaded', function () {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.lang = 'en-US';
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    const startSpeechRecognitionButton = document.getElementById('start-speech-recognition');

    // Add the speech recognition check here
    if (!SpeechRecognition) {
        startSpeechRecognitionButton.disabled = true;
        startSpeechRecognitionButton.textContent = 'Speech Recognition Not Supported';
    } else {
        startSpeechRecognitionButton.addEventListener('click', function () {
            recognition.start();
        });

        recognition.addEventListener('result', function (event) {
            const userInput = event.results[0][0].transcript;
            document.getElementById('user-input').value = userInput;
            document.getElementById('chat-form').submit();
        });

        recognition.addEventListener('error', function (event) {
            console.error('Speech recognition error:', event.error);
        });

        recognition.addEventListener('start', function () {
            console.log('Speech recognition started');
        });

        recognition.addEventListener('end', function () {
            console.log('Speech recognition ended');
        });
    }
});


function createTypingIndicator() {
    let msg = $('<div>').addClass('message').addClass('bot').attr('id', 'typing-indicator');
    let label = $('<div>').addClass('label').addClass('bot-label').text('Chatbot');
    let content = $('<div>').addClass('typing-indicator');
    let spinner = $('<span>').addClass('spinner');
    content.append(spinner).append('&nbsp;Chatbot is typing...');
    msg.append(label).append(content);
    return msg;
}

function markdownToHtml(text) {
    const lines = text.split('\n');
    let inCodeBlock = false;
    let language = '';
    for (let i = 0; i < lines.length; i++) {
        if (lines[i].startsWith('```')) {
            if (inCodeBlock) {
                // End of code block
                lines[i] = '</code></pre><button class="copy-button">Copy code</button>';
                inCodeBlock = false;
            } else {
                // Start of code block
                language = lines[i].substring(3) || '';
                lines[i] = '<pre><code class="' + language + '">';
                inCodeBlock = true;
            }
        }
    }
    return lines.join('<br>');
}


function appendMessage(who, text) {
    let msg = $('<div>').addClass('message').addClass(who === 'user' ? 'user' : 'bot');
    let label = $('<div>').addClass('label').addClass(who === 'user' ? 'user-label' : 'bot-label').text(who === 'user' ? 'You' : 'Chatbot');
    let replacedText = markdownToHtml(text);
    let content = $('<div>').html(replacedText.startsWith('<pre>') && replacedText.endsWith('</pre>') ? replacedText + '<button class="copy-button">Copy code</button>' : replacedText);
        msg.append(label).append(content);
    $('#chatbox').append(msg);
    $('#chatbox').scrollTop($('#chatbox')[0].scrollHeight);

    // Add the "Copy to clipboard" button to all code blocks
    content.find('pre code').each(function () {
        addCopyToClipboardButton(this);
    });
}


function showTypingIndicator() {
    let typingIndicator = createTypingIndicator();
    $('#chatbox').append(typingIndicator);
    $('#chatbox').scrollTop($('#chatbox')[0].scrollHeight);
}

function hideTypingIndicator() {
    $('#typing-indicator').remove();
}

function addCopyToClipboardButton(codeBlock) {
    const copyButton = document.createElement('button');
    copyButton.textContent = 'Copy code';
    copyButton.classList.add('copy-button');

    copyButton.addEventListener('click', () => {
        const textToCopy = codeBlock.tagName.toLowerCase() === 'code' ? codeBlock.innerText : codeBlock.textContent;
        navigator.clipboard.writeText(textToCopy).then(() => {
            // Show a success message or change the button text to "Copied!"
            copyButton.textContent = 'Copied!';
            setTimeout(() => {
                copyButton.textContent = 'Copy code';
            }, 2000);
        }).catch((error) => {
            console.error('Error copying to clipboard:', error);
        });
    });

    codeBlock.parentElement.insertBefore(copyButton, codeBlock);
}

function sendCommand(command) {
    if (!['reset', 'archive'].includes(command)) {
        return;
    }

    if (confirm(`Are you sure you want to ${command} the chat?`)) {
        showTypingIndicator();
        sendMessage('', command);
    }
}

$('#chat-form').on('submit', function (event) {
    event.preventDefault();

    let userInput = $('#user-input').val();
    let actionSelector = $('#action-selector').val();

    appendMessage('user', userInput);
    $('#user-input').val('');

    showTypingIndicator();
    sendMessage(userInput, actionSelector)
});

function sendMessage(userInput, actionSelector) {
    $.post('/message', { input: userInput, action: actionSelector }, function (data) {
        if (data.response_type === 'error') {
            hideTypingIndicator();
            alert("An error occurred: " + data.response);
        } else {
            hideTypingIndicator();
            appendMessage('bot', data.response);
        }
    });
}


setInterval(function () {
    let visibleDots = 0;
    $('#typing-indicator .dot').each(function () {
        let dot = $(this);
        setTimeout(function () {
            dot.css('opacity', visibleDots < 3 ? '1' : '0');
        }, visibleDots * 500);
        visibleDots = (visibleDots + 1) % 4;
    });
}, 1500);


function openSystemModal() {
    // Fetch the system content from the server
    $.get('/system', function (data) {
        $('#system-content-input').val(data.content); // Populate the textarea with the system content
        $('#systemModal').modal('show'); // Show the modal
    });
}

function saveSystemContent() {
    var content = $('#system-content-input').val(); // Get the updated system content from the textarea

    // Send a POST request to update the system content
    $.post('/system', { content: content }, function (data) {
        alert(data.message); // Show a success message
        $('#systemModal').modal('hide'); // Hide the modal
    });
}
