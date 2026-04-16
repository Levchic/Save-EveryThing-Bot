from aiogram.fsm.state import State, StatesGroup


class DownloadStates(StatesGroup):
    waiting_link = State()
    chose_type = State()      # video / audio
    chose_quality = State()   # format_id
    downloading = State()
    chose_playlist_action = State() # download all / download one by one    