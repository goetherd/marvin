from marvinbot.celeryapp import marvinbot_app, adapter_generator as make_adapter
from marvinbot.handlers import Filters
from marvinbot.cache import cache
from celery.utils.log import get_task_logger
from telegram.error import NetworkError, Unauthorized


log = get_task_logger(__name__)
adapter = make_adapter()

LOCK_EXPIRE = 60*5


@marvinbot_app.task(bind=True)
def fetch_messages(self):
    lock_id = '{0}-lock'.format(self.name)

    # cache.add fails if the key already exists
    acquire_lock = lambda: cache.get_or_create(lock_id, lambda: True, LOCK_EXPIRE)
    # memcache delete is very slow, but we have to use it to take
    # advantage of using add() for atomic locking
    release_lock = lambda: cache.delete(lock_id)

    if acquire_lock():
        try:
            for update in adapter.fetch_updates(cache.get('last_update_id', ignore_expiration=True)):
                adapter.process_update(update)
                cache.set('last_update_id', update.update_id + 1)
        except NetworkError:
            log.info("No more updates to fetch")
        except Unauthorized:
            # The user has removed or blocked the bot.
            log.error("Unauthorized: User might have blocked a bot")
        finally:
            release_lock()
    else:
        log.info("Another fetch_message operation is already running")


@adapter.register_command('start')
@marvinbot_app.task()
def start_command(update, *args):
    log.info('Start command caught')
    adapter.bot.sendMessage(chat_id=update.message.chat_id, text="I'm a bot, please talk to me!: {}".format(args))


@adapter.register_message_handler(Filters.photo)
@marvinbot_app.task()
def gaze_at_pic(update):
    update.message.reply_text('Nice pic, bro')


@adapter.register_message_handler([Filters.text, lambda msg: msg.text in ['hola', 'hi', 'klk', 'hey']],
                                  strict=True)
@marvinbot_app.task()
def salutation_initiative(update):
    update.message.reply_text("'zup")
