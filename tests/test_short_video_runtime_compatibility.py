from app.backend.runtime import create_backend_module


def test_short_video_module_loads_in_shared_backend_namespace():
    backend = create_backend_module()

    assert callable(backend.list_short_video_projects)
    assert callable(backend.create_short_video_project)
    assert callable(backend.request_short_video_render)
    assert callable(backend.short_video_candidate_file)
