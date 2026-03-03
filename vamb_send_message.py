from chatbot_utils.vamb import JWTVambManager, MetadataManager, VambConversation


def main() -> None:
    metadata_manager = MetadataManager()
    jwt_manager = JWTVambManager()
    conversation = VambConversation(jwt_manager, metadata_manager)

    try:
        conversation.initiate_conversation()
        response = conversation.send_message("Bok, RAIA!")
        print(response)
    except Exception as exc:
        print(exc)


if __name__ == "__main__":
    main()
