from collections import defaultdict, OrderedDict
from marvinbot.errors import HandlerException
from marvinbot.defaults import DEFAULT_PRIORITY
from marvinbot.models import User
from marvinbot.cache import cache
from marvinbot.plugins import Plugin
import telegram
import logging


log = logging.getLogger(__name__)
PERIODIC_TASKS = OrderedDict()


_ADAPTER = None
BANNED_IDS_CACHE_KEY = 'marvinbot-banned-user-ids'


def configure_adapter(config):
    global _ADAPTER
    _ADAPTER = TelegramAdapter(config)
    return _ADAPTER


def get_adapter():
    global _ADAPTER
    if _ADAPTER:
        return _ADAPTER


def is_user_banned(user_id):
    def get_banned_user_ids():
        return list(User.objects.filter(banned=True).scalar('id'))
    banned_ids = cache.get_or_create(BANNED_IDS_CACHE_KEY, get_banned_user_ids,
                                     should_cache_fn=lambda value: value is not None)
    return user_id in banned_ids


class TelegramAdapter(object):
    def __init__(self, config):
        token = config.get('telegram_token')
        self.config = config
        self.bot = telegram.Bot(token)
        self.handlers = defaultdict(list)
        self.plugin_registry = {}
        self.bot_info = self.bot.getMe()

    def fetch_updates(self, last_update_id=None):
        for update in self.bot.getUpdates(offset=last_update_id, timeout=int(self.config.get('fetch_timeout', 5))):
            yield update

    def add_handler(self, handler, priority=DEFAULT_PRIORITY, plugin=None):
        if not plugin:
            plugin = self.plugin_for_handler(handler)
        handler.plugin = plugin

        log.info("Adding handler: {}, priority: {}, plugin: {}".format(handler, priority, plugin))
        self.handlers[priority].append(handler)

    def plugin_for_handler(self, handler):
        mod = handler.callback.__module__.split('.', 1)[0]
        plugins = self.plugins_by_modspec()
        if mod in plugins:
            return plugins[mod]

    def plugins_by_modspec(self):
        return {p.modspec: p for p in self.plugin_registry.values()}

    def process_update(self, update):
        user_id = update.callback_query.from_user.id if update.callback_query else update.message.from_user.id
        if is_user_banned(user_id):
            return
        log.debug("Processing update: %s", update)
        for priority in sorted(self.handlers):
            for handler in self.handlers[priority]:
                try:
                    log.debug('Trying handler: %s', str(handler))
                    if handler.plugin and not handler.plugin.enabled:
                        continue
                    if handler.can_handle(update):
                        log.debug('Using handler: %s', str(handler))
                        handler.process_update(update)
                        return
                except Exception as e:
                    log.exception(e)
                    # self.notify_owners(r"⚠ Handler Error: ```{}```".format(traceback.format_exc()))
                    raise HandlerException from e

    def notify_owners(self, message, parse_mode='Markdown'):
        owners = User.objects.filter(role='owner')
        for owner in owners:
            self.bot.sendMessage(owner.id, message, parse_mode=parse_mode)

    def add_plugin(self, plugin):
        if not isinstance(plugin, Plugin):
            raise ValueError('plugin must be a Plugin sublass')
        self.plugin_registry[plugin.name] = plugin

    def enable_plugin(self, plugin_name, enable=True):
        if plugin_name in self.plugin_registry:
            self.plugin_registry[plugin_name].enabled = enable

    def plugin_definition(self, plugin_name):
        return self.plugin_registry.get(plugin_name)

    def commands(self, exclude_internal=False):
        from marvinbot.handlers import CommandHandler
        result = OrderedDict()
        for priority, handlers in self.handlers.items():
            if exclude_internal and priority == 0:
                continue
            for handler in handlers:
                if exclude_internal and handler.plugin is None:
                    continue
                if isinstance(handler, CommandHandler):
                    result[handler.command] = handler
        return result

    @property
    def scheduler_available(self):
        return hasattr(self, 'scheduler') and self.scheduler

    def add_job(self, func, *args, **kwargs):
        if not self.scheduler_available:
            raise ValueError('Scheduler not available')

        # Add the adapter for easy reference
        func.adapter = self
        return self.scheduler.add_job(func, *args, **kwargs)

    def pause_job(self, job_id):
        if not self.scheduler_available:
            raise ValueError('Scheduler not available')
        return self.scheduler.pause_job(job_id)

    def resume_job(self, job_id):
        if not self.scheduler_available:
            raise ValueError('Scheduler not available')
        return self.scheduler.resume_job(job_id)

    def remove_job(self, job_id):
        if not self.scheduler_available:
            raise ValueError('Scheduler not available')
        return self.scheduler.remove_job(job_id)

    def get_jobs(self):
        if not self.scheduler_available:
            raise ValueError('Scheduler not available')
        return self.scheduler.get_jobs()

    def get_job(self, job_id):
        if not self.scheduler_available:
            raise ValueError('Scheduler not available')
        return self.scheduler.get_job(job_id)
