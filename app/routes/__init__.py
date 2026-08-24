def register_blueprints(app):
    from app.routes import api, auth, backups, console, core, editor, files, launcher, misc, players, public, servers, settings

    app.register_blueprint(auth.bp)
    app.register_blueprint(misc.bp)
    app.register_blueprint(public.bp)
    app.register_blueprint(launcher.bp)
    app.register_blueprint(servers.bp)
    app.register_blueprint(console.bp)
    app.register_blueprint(players.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(files.bp)
    app.register_blueprint(editor.bp)
    app.register_blueprint(backups.bp)
    app.register_blueprint(core.bp)
    app.register_blueprint(api.bp)
