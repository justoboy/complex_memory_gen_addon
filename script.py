import json
import os
import re

import gradio as gr
import modules.chat as chat
import yaml
from modules import shared
from modules import text_generation
from modules.utils import gradio

settings = {}
# Initialize the current character
character = shared.settings["character"]
# Initialize the current progress
progress = 0


def count_tokens(text):
    # try:
    tokens = text_generation.get_encoded_length(text)
    return tokens
    # except:
    #    return 0


def save_memories(memories):
    global character
    if character is not None and character != "None":
        filename = f"characters/{character}.yaml"
    else:
        filename = "extensions/complex_memory/saved_memories.yaml"

    # read the current character file
    if os.path.exists(filename):
        with open(filename, 'r') as f:
            # Load the YAML data from the file into a Python dictionary
            data = yaml.load(f, Loader=yaml.Loader)
    else:
        data = {}

    # update the character file to include or update the memory
    data["memory"] += memories

    # write the character file again
    with open(filename, 'w') as f:
        yaml.dump(data, f, indent=2)


def save_settings():
    global settings
    filename = "extensions/complex_memory_gen_addon/settings.json"
    with open(filename, 'w') as f:
        json.dump(settings, f, indent=2)


def load_settings():
    global settings
    filename = "extensions/complex_memory_gen_addon/settings.json"
    try:
        with open(filename, 'r') as f:
            # Load the YAML data from the file into a Python dictionary
            data = json.load(f)
        if data:
            if {"instruction", "count", "chunk_size", "primer"} == set(data):
                settings = data
            else:
                print("Error: Invalid settings!")
                print("Download the default here https://github.com/justoboy/complex_memory_gen_addon/blob/main"
                      "/settings.json and place in text-generation-webui/extensions/complex_memory_gen_addon/")
                raise gr.Error("CMGA Invalid Settings!")
    except FileNotFoundError:
        print("Error: settings.json missing!")
        print("Download the default here https://github.com/justoboy/complex_memory_gen_addon/blob/main/settings.json "
              "and place in text-generation-webui/extensions/complex_memory_gen_addon/")
        raise gr.Error("CMGA Missing Settings!")


def update_settings(instruction, count, chunk_size, primer):
    global settings
    settings['instruction'] = instruction
    settings['count'] = count
    settings['chunk_size'] = chunk_size
    settings['primer'] = primer
    save_settings()


def setup():
    load_settings()


def generate_memories(unique_id, name1, name2, max_seq_len, state):
    prompt = load_chat(unique_id, name1, name2, max_seq_len)
    if prompt is None:
        raise gr.Warning("Current model has generated memories for entire chat-log!")
    else:
        for reply in text_generation.generate_reply(prompt, state):
            yield reply


def convert_memories(output):
    try:
        codeblock = re.findall("\\[.+\\{.+}.+]", output.replace("\n", ''))
        if len(codeblock) > 0:
            output = codeblock[0]
        json_memories = json.loads(output)
        return json_memories
    except json.JSONDecodeError as err:
        print(codeblock)
        return err


def add_memories(output, chat_id):
    global character
    memories = convert_memories(output)
    if type(memories) is not json.JSONDecodeError:
        save_memories(memories)
    else:
        raise gr.Error("Invalid json!")
    save_progress(chat_id)


def update_character(char_menu):
    global character
    character = char_menu


def ui():
    with gr.Accordion("", open=True):
        t_m = gr.Tab("Generate", elem_id="complex_memory_gen_tab_generate")
        with t_m:
            # Button to generate memories
            generate_button = gr.Button("Generate")

            # Textbox to show LLM output
            output = gr.Textbox(interactive=False, label="Output", placeholder="")

            # Fill output textbox on generate click
            generate_button.click(generate_memories,
                                  [shared.gradio[k] for k in ["unique_id", "name1", "name2", "max_seq_len"]] + gradio(
                                      'interface_state'),
                                  output)

            # Button to add new memories
            add_button = gr.Button("add")
            add_button.click(add_memories, [output, shared.gradio["unique_id"]])

        t_s = gr.Tab("Settings", elem_id="complex_memory_gen_tab_settings")
        with t_s:
            # Input for number of chat messages to sample
            chunk_size = gr.Number(label="Chunk Size", value=settings["chunk_size"], precision=0, minimum=1,
                                   maximum=250)
            # Input for number of memories to generate
            count = gr.Number(label="Count", value=settings["count"], precision=0, minimum=1, maximum=25)
            # Textbox for the LLMs instructions on how to format memories
            instruction = gr.Textbox(label="Instruction", value=settings['instruction'],
                                     lines=len(settings["instruction"].split('\n')))
            primer = gr.Textbox(label="Primer", value=settings['primer'],
                                lines=len(settings["primer"].split('\n')))
            chunk_size.change(update_settings, [instruction, count, chunk_size, primer])
            count.change(update_settings, [instruction, count, chunk_size, primer])
            instruction.change(update_settings, [instruction, count, chunk_size, primer])
            primer.change(update_settings, [instruction, count, chunk_size, primer])

    # We need to hijack load_character in order to load our memories based on characters.
    if 'character_menu' in shared.gradio:
        shared.gradio['character_menu'].change(
            update_character,
            [shared.gradio['character_menu']],
            None).then(
            chat.redraw_html, shared.reload_inputs, shared.gradio['display'])


def load_chat(chat_id, user, char, max_seq_len):
    """
    Loads a chat log from a JSON file and constructs a prompt for memory generation.

    :param str chat_id: The unique identifier for the chat log.
    :param str user: The name of the user.
    :param str char: The name of the character.
    :param int max_seq_len: The maximum number of tokens to return.

    :return: The prompt for memory generation, or None if the entire chat log has been processed.
    :rtype: str or None
    """
    global character, progress
    with open(f"logs/chat/{character}/{chat_id}.json", 'r') as f:
        chat_json = json.load(f)
    chat_json = chat_json["internal"]
    chat_str = settings["instruction"].replace('{char}', char).replace('{count}', str(settings["count"]))
    primer = settings["primer"].replace('{char}', char).replace('{count}', str(settings["count"]))
    if chat_str[-1] != '\n':
        chat_str += '\n'
    i = load_progress(chat_id)
    j = 0
    while j < settings['chunk_size'] and i < len(chat_json):
        if chat_json[i][0] == "<|BEGIN-VISIBLE-CHAT|>":
            chat_str += f"{char}: {chat_json[i][1]}\n"
            j += 1
        else:
            if count_tokens(chat_str + f"{user}: {chat_json[i][0]}\n{char}: {chat_json[i][1]}\n\n" +
                            primer) > max_seq_len:
                break
            chat_str += f"{user}: {chat_json[i][0]}\n{char}: {chat_json[i][1]}\n"
            j += 2
        i += 1
    progress = i
    if j > 0:
        return chat_str + "\n" + primer
    else:
        return None


def save_progress(chat_id):
    """
    Saves the current progress in processing the chat log for memory generation.

    :param: str chat_id: The unique identifier for the chat log.
    """
    global character, progress
    try:
        with open("extensions/complex_memory_gen_addon/save.json", 'r') as f:
            save_json = json.load(f)
    except FileNotFoundError:
        save_json = {}

    save_json.setdefault(shared.model_name, {}).setdefault(character, {})[chat_id] = progress

    with open("extensions/complex_memory_gen_addon/save.json", 'w') as f:
        json.dump(save_json, f)


def load_progress(chat_id):
    """
    Loads the current progress in processing the chat log for memory generation.

    :param str chat_id: The unique identifier for the chat log.

    :return: The current progress index, or 0 if no progress has been saved.
    :rtype: int
    """
    global character, progress
    try:
        with open("extensions/complex_memory_gen_addon/save.json", 'r') as f:
            save_json = json.load(f)
    except FileNotFoundError:
        progress = 0
        save_progress(chat_id)
        return 0

    try:
        return save_json[shared.model_name][character][chat_id]
    except KeyError:
        progress = 0
        save_progress(chat_id)
        return 0
